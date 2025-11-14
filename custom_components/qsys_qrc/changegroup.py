import asyncio
import logging
from enum import Enum, auto
import contextlib

from .qsys import qrc
from .const import CONF_POLL_INTERVAL, CONF_REQUEST_TIMEOUT

_LOGGER = logging.getLogger(__name__)


def create_change_group_for_platform(core, change_group_config, platform):
    change_group_config = change_group_config or {}
    return ChangeGroupPoller(
        core,
        f"{platform}_platform",
        change_group_config.get(CONF_POLL_INTERVAL, 1.0),
        change_group_config.get(CONF_REQUEST_TIMEOUT, 5.0),
    )


class PollerState(Enum):
    IDLE = auto()          # Not started
    STARTING = auto()      # Waiting for core connectivity & creating CG
    RUNNING = auto()       # Polling loop active
    STOPPING = auto()      # Stop requested, cleaning up


class ChangeGroupPoller:
    """Polls a Q-Sys Change Group and dispatches control change events.

    Responsibilities:
    - Wait for Core connection
    - (Re)create change group after reconnect
    - Poll for changes at interval
    - Notify listeners
    - Resilient against timeouts, QRCError, generic exceptions
    """

    def __init__(self, core: qrc.Core, change_group_name, poll_interval, request_timeout):
        self.core = core
        self._listeners_component_control = []  # (listener, filter)
        self._listeners_run_loop_iteration_ending = []
        self._listeners_component_control_changes = {}  # (component, control) -> [listeners]
        self._change_group_name = change_group_name
        self.cg = None
        self._poll_interval = poll_interval
        self._request_timeout = request_timeout

        # state & coordination
        self._state = PollerState.IDLE
        self._state_lock = asyncio.Lock()
        self._stop_event = asyncio.Event()
        self._started_event = asyncio.Event()
        self._loop_task = None
        self._creation_count = 0  # number of times change group created/recreated

    async def _set_state(self, new_state: PollerState):
        async with self._state_lock:
            old = self._state
            self._state = new_state
            _LOGGER.debug("ChangeGroupPoller[%s] state: %s -> %s", self._change_group_name, old.name, new_state.name)
            if new_state == PollerState.RUNNING:
                self._started_event.set()
            if new_state in (PollerState.IDLE, PollerState.STOPPING):
                self._started_event.clear()

    async def wait_until_running(self, timeout=None):
        await asyncio.wait_for(self._started_event.wait(), timeout)

    def subscribe_component_control(self, listener, filter):
        self._listeners_component_control.append((listener, filter))

    async def _fire_on_component_control(self, component, control):
        for listener, filter in self._listeners_component_control:
            if filter(component, control):
                if asyncio.iscoroutine(listener) or asyncio.iscoroutinefunction(
                    listener
                ):
                    await listener(self, component, control)
                else:
                    listener(self, component, control)

    def subscribe_run_loop_iteration_ending(self, listener):
        self._listeners_run_loop_iteration_ending.append(listener)

    async def _fire_on_run_loop_iteration_ending(self):
        for listener in self._listeners_run_loop_iteration_ending:
            if asyncio.iscoroutine(listener) or asyncio.iscoroutinefunction(listener):
                await listener(self)
            else:
                listener(self)

    async def subscribe_component_control_changes(
        self, listener, component_name, control_name
    ):
        self._listeners_component_control_changes.setdefault(
            (component_name, control_name), []
        ).append(listener)

        # If change group already created, add control immediately (best-effort)
        if self.cg:
            try:
                await asyncio.wait_for(
                    self.cg.add_component_control(
                        {
                            "Name": component_name,
                            "Controls": [{"Name": control_name}],
                        }
                    ),
                    timeout=self._request_timeout,
                )
            except Exception as ex:  # noqa: BLE001
                _LOGGER.warning(
                    "Unable to add component control immediately (%s/%s): %s",
                    component_name,
                    control_name,
                    repr(ex),
                )

    async def _fire_on_component_control_change(self, change):
        component_name = change["Component"]
        control_name = change["Name"]

        for listener in self._listeners_component_control_changes.get(
            (component_name, control_name), []
        ):
            if asyncio.iscoroutine(listener) or asyncio.iscoroutinefunction(listener):
                await listener(self, change)
            else:
                listener(self, change)

    async def _create_or_recreate_change_group(self):
        self.cg = self.core.change_group(self._change_group_name)
        _LOGGER.info(
            "%s: creating changegroup with %d controls, poll interval: %f, request timeout: %f",
            self._change_group_name,
            len(self._listeners_component_control_changes),
            self._poll_interval,
            self._request_timeout,
        )
        self._creation_count += 1
        # add all subscribed controls
        for (component_name, control_name), _listeners in self._listeners_component_control_changes.items():
            try:
                await asyncio.wait_for(
                    self.cg.add_component_control(
                        {
                            "Name": component_name,
                            "Controls": [{"Name": control_name}],
                        }
                    ),
                    timeout=self._request_timeout,
                )
            except Exception as ex:  # noqa: BLE001
                _LOGGER.warning(
                    "%s: unable to add control %s/%s: %s",
                    self._change_group_name,
                    component_name,
                    control_name,
                    repr(ex),
                )

    async def _poll_once(self):
        if not self.cg:
            return
        poll_result = await asyncio.wait_for(self.cg.poll(), timeout=self._request_timeout)
        _LOGGER.debug("%s poll result: %s", self._change_group_name, poll_result)
        for change in poll_result.get("result", {}).get("Changes", []):
            await self._fire_on_component_control_change(change)

    async def _run_loop(self):
        while not self._stop_event.is_set():
            try:
                await self._set_state(PollerState.STARTING)
                # Wait for connection; if already connected continues immediately
                await self.core.wait_until_connected()
                await self._create_or_recreate_change_group()
                await self._set_state(PollerState.RUNNING)

                # inner polling loop; break on disconnection or stop
                while not self._stop_event.is_set():
                    # If core lost connection, break to outer loop to recreate
                    if not self.core._connected_event.is_set():  # relies on Core event; stub cores mimic this
                        _LOGGER.debug("%s: core disconnected detected, leaving inner loop", self._change_group_name)
                        # Clear existing change group reference so recreation definitely occurs
                        self.cg = None
                        break
                    await self._poll_once()
                    await asyncio.sleep(self._poll_interval)

            except TimeoutError as ex:
                _LOGGER.warning(
                    "Timeout during changegroup operation %s: %s",
                    self._change_group_name,
                    repr(ex),
                )
            except qrc.QRCError as ex:
                _LOGGER.info(
                    "Change group %s probably invalid after reconnect: %s, will recreate",
                    self._change_group_name,
                    repr(ex),
                )
            except asyncio.CancelledError:
                # propagate cancellation
                raise
            except Exception as ex:  # noqa: BLE001
                _LOGGER.exception(
                    "Unexpected error in changegroup poller %s: %s",
                    self._change_group_name,
                    repr(ex),
                )
            finally:
                await self._fire_on_run_loop_iteration_ending()
                # short pause before attempting to restart after error (unless stopping)
                if not self._stop_event.is_set():
                    await asyncio.sleep(self._poll_interval)

        await self._set_state(PollerState.STOPPING)
        self.cg = None
        await self._set_state(PollerState.IDLE)

    def start(self):
        if self._loop_task and not self._loop_task.done():
            return self._loop_task
        self._stop_event.clear()
        self._loop_task = asyncio.create_task(self._run_loop())
        return self._loop_task

    async def stop(self):
        """Request poller stop and wait for graceful shutdown.

        We first signal the loop to exit so it can perform final state
        transitions (STOPPING -> IDLE). If the loop does not finish within
        a bounded timeout we cancel it as a fallback.
        """
        self._stop_event.set()
        if self._loop_task:
            # Allow loop to exit naturally (bounded by one poll + sleep)
            graceful_timeout = self._poll_interval + self._request_timeout + 0.2
            try:
                await asyncio.wait_for(self._loop_task, timeout=graceful_timeout)
            except TimeoutError:
                _LOGGER.debug("Graceful stop timeout; cancelling poller task")
                self._loop_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._loop_task
            except asyncio.CancelledError:
                # If externally cancelled propagate after cleanup
                raise
            finally:
                self._loop_task = None

    # Backward compatible entrypoint
    async def run_while_core_running(self):  # pragma: no cover - thin wrapper
        self.start()
        try:
            await self._loop_task
        except asyncio.CancelledError:
            raise
