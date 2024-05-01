import asyncio
import logging
import sys

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


class ChangeGroupPoller:
    def __init__(
        self, core: qrc.Core, change_group_name, poll_interval, request_timeout
    ):
        self.core = core
        self._listeners_component_control = []
        self._listeners_run_loop_iteration_ending = []
        self._listeners_component_control_changes = {}
        self._change_group_name = change_group_name
        self.cg = None
        self._poll_interval = poll_interval
        self._request_timeout = request_timeout

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

        if self.cg:
            await self.cg.add_component_control(
                {
                    "Name": component_name,
                    "Controls": [{"Name": control_name}],
                }
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

    async def run_while_core_running(self):
        while True:
            try:
                # TODO: run_while_core_is_running?
                await self.core.wait_until_connected()

                # recreate change group
                self.cg = self.core.change_group(self._change_group_name)

                _LOGGER.info(
                    "%s: creating changegroup with %d controls, poll interval: %f, request timeout: %f",
                    self._change_group_name,
                    len(self._listeners_component_control_changes),
                    self._poll_interval,
                    self._request_timeout,
                )
                for (
                    component_name,
                    control_name,
                ), listeners in self._listeners_component_control_changes.items():
                    await asyncio.wait_for(
                        self.cg.add_component_control(
                            {
                                "Name": component_name,
                                "Controls": [{"Name": control_name}],
                            }
                        ),
                        self._request_timeout,
                    )

                while True:
                    # TODO: find a way to only poll if there are components to poll
                    _LOGGER.debug("%s: polling", self._change_group_name)
                    poll_result = await asyncio.wait_for(
                        self.cg.poll(), self._request_timeout
                    )
                    _LOGGER.debug(
                        "%s poll result: %s", self._change_group_name, poll_result
                    )

                    for change in poll_result["result"]["Changes"]:
                        await self._fire_on_component_control_change(change)
                    await asyncio.sleep(self._poll_interval)

            except TimeoutError as ex:
                # we poll with a timeout
                _LOGGER.warning(
                    "Timeout error during polling %s: %s",
                    self._change_group_name,
                    repr(ex),
                )

            except qrc.QRCError as ex:
                _LOGGER.info(
                    "Change group %s probably didn't exist because of a reconnect: %s, retrying",
                    self._change_group_name,
                    repr(ex),
                )

            except asyncio.CancelledError as err:
                # re-raise to avoid hitting the generic exception handler below
                raise err

            except Exception as ex:  # pylint: disable=broad-except
                _LOGGER.exception(
                    "Error during polling %s: %s", self._change_group_name, repr(ex)
                )

            finally:
                await self._fire_on_run_loop_iteration_ending()
                if not sys.exception():
                    await asyncio.sleep(self._poll_interval)
