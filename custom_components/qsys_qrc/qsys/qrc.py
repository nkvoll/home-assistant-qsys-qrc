import asyncio
import contextlib
import json
import logging
from enum import Enum, auto

_LOGGER = logging.getLogger(__name__)

DELIMITER = b"\0"

PORT = 1710

error_codes = {
    -32700: "Parse error. Invalid JSON was received by the server.",
    -32600: "Invalid request. The JSON sent is not a valid Request object.",
    -32601: "Method not found.",
    -32602: "Invalid params.",
    -32603: "Server error.",
    2: "Invalid Page Request ID",
    3: "Bad Page Request - could not create the requested Page Request",
    4: "Missing file",
    5: "Change Groups exhausted",
    6: "Unknown change group",
    7: "Unknown component name",
    8: "Unknown control",
    9: "Illegal mixer channel index",
    10: "Logon required",
}


class QRCError(Exception):
    def __init__(self, err):
        self.error = err


class ConnectionState(Enum):
    """Connection state for the Q-Sys Core."""
    DISCONNECTED = auto()
    CONNECTING = auto()
    CONNECTED = auto()
    STOPPING = auto()


class Core:
    """Q-Sys Core connection manager with JSON-RPC support.

    Timing knobs (for tests / tuning):
    - backoff_initial: starting reconnect delay
    - backoff_multiplier: multiplier applied after each failed cycle
    - backoff_max: maximum reconnect delay
    - connect_timeout: timeout used for initial asyncio.open_connection
    - sleep_func: injectable sleep coroutine (defaults to asyncio.sleep)
    """

    def __init__(
        self,
        host,
        port: int = PORT,
        *,
        backoff_initial: float = 1.0,
        backoff_multiplier: float = 1.5,
        backoff_max: float = 60.0,
        connect_timeout: float = 5.0,
        sleep_func=asyncio.sleep,
    ):
        self._host = host
        self._port = port

        # Connection state
        self._state = ConnectionState.DISCONNECTED
        self._state_lock = asyncio.Lock()

        # Events for coordination
        self._connected_event = asyncio.Event()
        self._stop_event = asyncio.Event()

        # Connection resources
        self._reader = None
        self._writer = None
        self._reader_task = None

        # RPC state
        self._id = 0
        self._pending = {}

        # Hooks
        self._on_connected_commands = []

        # Timing configuration
        self._backoff_initial = backoff_initial
        self._backoff_multiplier = backoff_multiplier
        self._backoff_max = backoff_max
        self._connect_timeout = connect_timeout
        self._sleep = sleep_func

    def set_on_connected_commands(self, commands: list):
        """Set commands to execute when connected."""
        self._on_connected_commands = commands

    def _generate_id(self):
        """Generate a unique request ID."""
        self._id = (self._id + 1) % 65535
        return self._id

    async def get_state(self) -> ConnectionState:
        """Get current connection state."""
        async with self._state_lock:
            return self._state

    async def _set_state(self, new_state: ConnectionState):
        """Set connection state and update events."""
        async with self._state_lock:
            old_state = self._state
            self._state = new_state
            _LOGGER.debug("State transition: %s -> %s", old_state.name, new_state.name)

            if new_state == ConnectionState.CONNECTED:
                self._connected_event.set()
            else:
                self._connected_event.clear()

    async def wait_until_running(self):
        """Wait until the core is running. Deprecated: use wait_until_connected."""
        await self.wait_until_connected()

    async def wait_until_connected(self, timeout=None):
        """Wait until the core is connected."""
        await asyncio.wait_for(self._connected_event.wait(), timeout)

    async def connect(self):
        """Establish connection to Q-Sys core."""
        await self._set_state(ConnectionState.CONNECTING)
        _LOGGER.info("Connecting to %s:%d", self._host, self._port)
        # TODO: make limit configurable
        opening = asyncio.open_connection(
            self._host, self._port, limit=5 * 1024 * 1024,
        )
        self._reader, self._writer = await asyncio.wait_for(opening, self._connect_timeout)
        _LOGGER.info("Connected")

    async def _execute_on_connected_commands(self):
        """Execute commands that should run when connected."""
        for cmd in self._on_connected_commands:
            try:
                if asyncio.iscoroutine(cmd) or asyncio.iscoroutinefunction(cmd):
                    await cmd()
                elif callable(cmd):
                    cmd()
                else:
                    # TODO: if not dict, log warning or fail?
                    await self.call(
                        method=cmd["method"],
                        params=cmd.get("params", None)
                    )
            except Exception as ex:
                _LOGGER.error("Error executing on-connected command: %s", repr(ex))
                # TODO: support aborting connection (with backoff?) on failures

    async def _cleanup_connection(self):
        """Clean up connection resources and pending requests."""
        # Cancel reader task if running
        if self._reader_task and not self._reader_task.done():
            _LOGGER.debug("Cancelling reader task")
            self._reader_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._reader_task

        self._reader_task = None

        # Close writer
        if self._writer:
            try:
                _LOGGER.info("Closing writer")
                self._writer.close()
                await self._writer.wait_closed()
            except Exception as ex:
                _LOGGER.exception("Unable to close writer: %s", repr(ex))

        self._writer = None
        self._reader = None

        # Fail pending requests
        pending = list(self._pending.items())
        # Clear pending dict to prevent memory leaks
        self._pending.clear()

        for request_id, future in pending:
            if not future.done():
                future.set_exception(
                    QRCError({"code": -1, "message": "disconnected"})
                )

        await self._set_state(ConnectionState.DISCONNECTED)

    async def _handle_connection_cycle(self):
        """Handle a single connection attempt and its lifecycle."""
        try:
            # Connect to the core
            await self.connect()

            # Start reader task
            self._reader_task = asyncio.create_task(self._read_forever())

            # Mark as connected (this resolves the race condition)
            await self._set_state(ConnectionState.CONNECTED)

            # Execute on-connected commands
            await self._execute_on_connected_commands()

            # Wait for reader to finish (disconnect or error)
            await self._reader_task

        except EOFError:
            _LOGGER.info("EOF from core at [%s]", self._host)
        except TimeoutError:
            state = await self.get_state()
            if state == ConnectionState.CONNECTED:
                _LOGGER.warning(
                    "Timeout while reading from remote [%s:%d]",
                    self._host,
                    self._port,
                )
            else:
                _LOGGER.warning(
                    "Timeout while connecting to remote [%s:%d]",
                    self._host,
                    self._port,
                )
        except Exception as ex:
            _LOGGER.exception("Error in connection cycle: %s", repr(ex))
        finally:
            await self._cleanup_connection()

    async def run_until_stopped(self):
        """Run the core connection manager until stopped."""
        backoff = self._backoff_initial
        max_backoff = self._backoff_max

        while not self._stop_event.is_set():
            _LOGGER.debug("Run loop iteration")

            try:
                await self._handle_connection_cycle()
                backoff = self._backoff_initial  # Reset backoff on successful connection
            except asyncio.CancelledError:
                _LOGGER.info("Core task cancelled")
                raise
            except Exception as ex:
                _LOGGER.exception("Unexpected error in run loop: %s", repr(ex))

            # Wait before reconnecting (unless stopping)
            if not self._stop_event.is_set():
                _LOGGER.info("Reconnecting in %.3f seconds", backoff)
                try:
                    # Wait either for stop or backoff expiration
                    await asyncio.wait_for(self._stop_event.wait(), timeout=backoff)
                    break  # stop requested
                except asyncio.TimeoutError:
                    pass  # timeout -> attempt reconnect
                backoff = min(backoff * self._backoff_multiplier, max_backoff)

        _LOGGER.info("Core stopped")
        await self._set_state(ConnectionState.STOPPING)

    async def stop(self):
        """Stop the core and close connections."""
        self._stop_event.set()
        await self._cleanup_connection()

    async def _send(self, data):
        """Send JSON-RPC message to core."""
        # Wait until connected
        await self.wait_until_connected()

        # Check we're still connected after waiting
        state = await self.get_state()
        if state != ConnectionState.CONNECTED:
            raise QRCError({"code": -1, "message": "not connected"})

        data.setdefault("jsonrpc", "2.0")
        _LOGGER.debug("Sending message: %s", json.dumps(data).encode("utf8"))
        self._writer.write(json.dumps(data).encode("utf8"))
        self._writer.write(DELIMITER)

    async def call(self, method, params=None):
        params = {} if params is None else params

        future = asyncio.Future()
        id_ = self._generate_id()
        self._pending[id_] = future

        try:
            await self._send({"method": method, "params": params, "id": id_})

            result = await future
            return result
        finally:
            self._pending.pop(id_, None)

    async def _read_forever(self):
        while True:
            raw_data = await self._reader.readuntil(DELIMITER)
            data = json.loads(raw_data[:-1])
            if "id" in data:
                _LOGGER.debug("Received response: %s", data)
                await self._process_response(data)
            else:
                _LOGGER.debug("Received non-response: %s", data)

    async def _process_response(self, data):
        future = self._pending.pop(data["id"], None)
        if future and not future.done():
            if "error" in data:
                future.set_exception(QRCError(data["error"]))
            else:
                future.set_result(data)

    async def noop(self):
        return await self.call("NoOp")

    async def logon(self, username, password):
        return await self.call("Logon", params={"User": username, "Password": password})

    async def status_get(self):
        return await self.call("StatusGet")

    def component(self):
        return ComponentAPI(self)

    def change_group(self, id_):
        return ChangeGroupAPI(self, id_)


class ComponentAPI:
    def __init__(self, core: Core):
        self._core = core

    async def get_components(self):
        return await self._core.call("Component.GetComponents")

    async def get_controls(self, name):
        return await self._core.call("Component.GetControls", params={"Name": name})

    async def get(self, name, controls):
        return await self._core.call(
            "Component.Get", params={"Name": name, "Controls": controls}
        )

    async def set(self, name, controls):
        return await self._core.call(
            "Component.Set", params={"Name": name, "Controls": controls}
        )


class ChangeGroupAPI:
    def __init__(self, core: Core, id_: int):
        self._core = core
        self.id = id_

    async def add_component_control(self, component):
        return await self._core.call(
            "ChangeGroup.AddComponentControl",
            params={"Id": self.id, "Component": component},
        )

    async def poll(self):
        return await self._core.call("ChangeGroup.Poll", {"Id": self.id})
