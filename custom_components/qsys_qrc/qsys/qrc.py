import asyncio
import json
import logging
from asyncio import exceptions as aioexceptions

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


class Core:
    def __init__(self, host):
        self._host = host
        self._reader = None
        self._writer = None
        self._id = 0
        self._pending = {}
        self._running = asyncio.Future()
        self._connected = asyncio.Future()

        self._on_connected_commands = []

    def set_on_connected_commands(self, commands: list):
        self._on_connected_commands = commands

    def _generate_id(self):
        self._id = (self._id + 1) % 65535
        return self._id

    async def wait_until_running(self):
        await asyncio.shield(self._running)

    async def wait_until_connected(self):
        await asyncio.shield(self._connected)

    async def run_until_stopped(self):
        self._running.set_result(True)

        while True:
            _LOGGER.debug("Run loop iteration")
            reader = None
            try:
                await self.connect()
                reader = asyncio.Task(self._read_forever())
                # TODO: potential race here?
                self._connected.set_result(True)
                for cmd in self._on_connected_commands:
                    if asyncio.iscoroutine(cmd) or asyncio.iscoroutinefunction(cmd):
                        await cmd()
                    elif callable(cmd):
                        cmd()
                    else:
                        # TODO: support aborting connection (with backoff?) on failures
                        await self.call(
                            method=cmd["method"], params=cmd.get("params", None)
                        )
                await reader
            except EOFError as eof:
                _LOGGER.info("EOF from core at [%s]", self._host)
            except aioexceptions.TimeoutError as te:
                if self._connected.done():
                    _LOGGER.warning(
                        "Timeouterror while reading from remote [%s:%d]",
                        self._host,
                        PORT,
                    )
                else:
                    _LOGGER.warning(
                        "Timeouterror while connecting to remote [%s:%d]",
                        self._host,
                        PORT,
                    )
            except Exception as e:
                _LOGGER.exception("Generic exception: [%s]", repr(e))
                await asyncio.sleep(10)
            finally:
                if reader:
                    _LOGGER.debug("Cancelling reader")
                    reader.cancel()
                if self._writer:
                    self._writer.close()
                if self._connected.done():
                    _LOGGER.debug("Creating new _connected future")
                    self._connected = asyncio.Future()

                    # tell pending requests that we failed
                    for _, future in self._pending.items():
                        future.set_exception(
                            QRCError({"code": -1, "message": "disconnected"})
                        )

    async def connect(self):
        _LOGGER.info("Connecting to %s:%d", self._host, PORT)
        # TODO: make limit configurable
        opening = asyncio.open_connection(self._host, PORT, limit=5 * 1024 * 1024)
        self._reader, self._writer = await asyncio.wait_for(opening, 5)
        _LOGGER.info("Connected")

    async def _send(self, data):
        await asyncio.shield(self._running)
        await asyncio.shield(self._connected)
        data.setdefault("jsonrpc", "2.0")
        _LOGGER.debug("Sending message: %s", data)
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
        if future:
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
