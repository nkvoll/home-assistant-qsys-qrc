import traceback
import asyncio

from .qsys import core


class Hub:
    def __init__(self, c: core.Core):
        self.core = c
        self._listeners_component_control = []
        self._listeners_component_control_changes = dict()

    def subscribe_component_control(self, listener, filter):
        self._listeners_component_control.append((listener, filter))

    async def _fire_on_component_control(self, component, control):
        for (listener, filter) in self._listeners_component_control:
            if filter(component, control):
                if asyncio.iscoroutine(listener):
                    await listener(self, component, control)
                else:
                    listener(self, component, control)

    def subscribe_component_control_changes(
        self, listener, component_name, control_name
    ):
        self._listeners_component_control_changes.setdefault(
            (component_name, control_name), []
        ).append(listener)

    async def _fire_on_component_control_change(self, change):
        component_name = change["Component"]
        control_name = change["Name"]

        for listener in self._listeners_component_control_changes.get(
            (component_name, control_name), []
        ):
            if asyncio.iscoroutine(listener):
                await listener(self, change)
            else:
                listener(self, change)

    async def run_poll(self):
        while True:
            try:
                components = await self.core.component().get_components()

                cg = self.core.change_group("foo")
                for component in components["result"]:
                    controls = await self.core.component().get_controls(
                        component["Name"]
                    )

                    await cg.add_component_control(
                        {
                            "Name": component["Name"],
                            "Controls": [
                                {"Name": control["Name"]}
                                for control in controls["result"]["Controls"]
                            ],
                        }
                    )

                    for control in controls["result"]["Controls"]:
                        await self._fire_on_component_control(component, control)

                while True:
                    poll_result = await cg.poll()
                    print("poll", poll_result)

                    for change in poll_result["result"]["Changes"]:
                        await self._fire_on_component_control_change(change)
                    await asyncio.sleep(1)

            except Exception as e:
                print("error", e, repr(e))
                traceback.print_exc()
