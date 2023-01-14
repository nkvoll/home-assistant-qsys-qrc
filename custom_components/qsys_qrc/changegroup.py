import asyncio
import logging

from .qsys import qrc

_LOGGER = logging.getLogger(__name__)


class ChangeGroupPoller:
    def __init__(self, core: qrc.Core, change_group_name):
        self.core = core
        self._listeners_component_control = []
        self._listeners_component_control_changes = {}
        self._change_group_name = change_group_name
        self.cg = None

    def subscribe_component_control(self, listener, filter):
        self._listeners_component_control.append((listener, filter))

    async def _fire_on_component_control(self, component, control):
        for (listener, filter) in self._listeners_component_control:
            if filter(component, control):
                if asyncio.iscoroutine(listener) or asyncio.iscoroutinefunction(listener):
                    await listener(self, component, control)
                else:
                    listener(self, component, control)

    async def subscribe_component_control_changes(
            self, listener, component_name, control_name
    ):
        self._listeners_component_control_changes.setdefault(
            (component_name, control_name), []
        ).append(listener)

        if self.cg:
            await self.cg.add_component_control({
                "Name": component_name,
                "Controls": [
                    {"Name": control_name}
                ],
            })

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
                _LOGGER.info("waiting for core to connect")
                await self.core.wait_until_connected()

                # recreate change group
                self.cg = self.core.change_group(self._change_group_name)

                for ((component_name, control_name), listeners) in self._listeners_component_control_changes.items():
                    await self.cg.add_component_control({
                        "Name": component_name,
                        "Controls": [
                            {"Name": control_name}
                        ],
                    })

                while True:
                    # TODO: find a way to only poll if there are components to poll
                    poll_result = await self.cg.poll()
                    _LOGGER.debug("poll result: %s", poll_result)

                    for change in poll_result["result"]["Changes"]:
                        await self._fire_on_component_control_change(change)
                    await asyncio.sleep(1)

            except Exception as e:
                _LOGGER.exception("error during polling: %s", repr(e))