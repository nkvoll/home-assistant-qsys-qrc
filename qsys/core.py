import asyncio
import copyreg
import socket
import json
from time import sleep


DELIMITER = b"\0"

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
    6: "Unknown change croup",
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

    def _generate_id(self):
        self._id = (self._id + 1) % 65535
        return self._id

    async def wait_until_running(self):
        await self._running

    async def run_until_stopped(self):
        self._running.set_result(True)

        while True:
            print("run loop iteration")
            try:
                await self.connect()
                self._connected.set_result(True)
                await self._read_forever()
            except EOFError as eof:
                print("eof", eof)
            except Exception as e:
                print("generic exception", repr(e), e)
            finally:
                print("finally")
                if self._writer:
                    self._writer.close()
                if self._connected.done():
                    self._connected = asyncio.Future()

    async def connect(self):
        print("connecting")
        opening = asyncio.open_connection(self._host, 1710)
        self._reader, self._writer = await asyncio.wait_for(opening, 5)
        print("connected")

    async def _send(self, data):
        await self._running
        await self._connected
        data.setdefault("jsonrpc", "2.0")
        self._writer.write(json.dumps(data).encode("utf8"))
        self._writer.write(DELIMITER)

    async def _call(self, method, params=None):
        params = {} if params is None else params

        future = asyncio.Future()
        id_ = self._generate_id()
        self._pending[id_] = future

        await self._send({"method": method, "params": params, "id": id_})

        result = await future
        return result

    async def _read_forever(self):
        while True:
            raw_data = await self._reader.readuntil(DELIMITER)
            data = json.loads(raw_data[:-1])
            if "id" in data:
                await self._process_response(data)
            else:
                print("received non-response", data)

    async def _process_response(self, data):
        future = self._pending.pop(data["id"], None)
        if future:
            if "error" in data:
                future.set_exception(QRCError(data["error"]))
            else:
                future.set_result(data)

    async def noop(self):
        return await self._call("NoOp")

    async def logon(self, username, password):
        return await self._call(
            "Logon", params={"User": username, "Password": password}
        )

    def component(self):
        return ComponentAPI(self)

    def change_group(self, id_):
        return ChangeGroupAPI(self, id_)


class ComponentAPI:
    def __init__(self, core: Core):
        self._core = core

    async def get_components(self):
        return await self._core._call("Component.GetComponents")

    async def get_controls(self, name):
        return await self._core._call("Component.GetControls", params={"Name": name})

    async def set(self, name, controls):
        return await self._core._call("Component.Set", params={"Name": name, 'Controls': controls})

class ChangeGroupAPI:
    def __init__(self, core: Core, id_: int):
        self._core = core
        self.id = id_

    async def add_component_control(self, component):
        return await self._core._call(
            "ChangeGroup.AddComponentControl",
            params={"Id": self.id, "Component": component},
        )

    async def poll(self):
        return await self._core._call("ChangeGroup.Poll", {"Id": self.id})


async def main():
    core = Core("192.168.1.73")
    task = asyncio.create_task(core.run_until_stopped())

    print("noop", await core.noop())

    print("logon", await core.logon("foo", "bar"))

    componentapi = core.component()
    components = await componentapi.get_components()
    print(
        "components",
        [component["Name"] for component in components["result"]],
    )

    import sys

    print(await core.component().get_controls(sys.argv[1]))

    sys.exit(1)

    while True:
        try:
            cg = core.change_group("foo")
            for component in components["result"]:
                controls = await componentapi.get_controls(component["Name"])
                print(
                    "controls for",
                    component["Name"],
                    [control["Name"] for control in controls["result"]["Controls"]],
                )

                print(
                    "add component control",
                    await cg.add_component_control(
                        {
                            "Name": component["Name"],
                            "Controls": [
                                {"Name": control["Name"]}
                                for control in controls["result"]["Controls"]
                            ],
                        }
                    ),
                )

            while True:
                print("poll", await cg.poll())
                await asyncio.sleep(1)
        except QRCError as e:
            if e.error["code"] == 6:
                print("lost server side change group")
            continue

    await task


if __name__ == "__main__":
    asyncio.run(main())
    asyncio.run_forever()
