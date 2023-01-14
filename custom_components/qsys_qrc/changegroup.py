import asyncio
import logging

from .qsys import core

_LOGGER = logging.getLogger(__name__)


class ChangeGroupPoller:
    def __init__(self, c: core.Core, cg: core.ChangeGroupAPI):
        self.core = c
        self.cg = cg
        self._listeners_component_control = []
        self._listeners_component_control_changes = dict()

    def subscribe_component_control(self, listener, filter):
        self._listeners_component_control.append((listener, filter))

    async def _fire_on_component_control(self, component, control):
        for (listener, filter) in self._listeners_component_control:
            if filter(component, control):
                if asyncio.iscoroutine(listener) or asyncio.iscoroutinefunction(listener):
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
            if asyncio.iscoroutine(listener) or asyncio.iscoroutinefunction(listener):
                await listener(self, change)
            else:
                listener(self, change)

    async def run_poll(self):
        while True:
            try:
                while True:
                    # TODO: find a way to only poll if there are components to poll
                    poll_result = await self.cg.poll()
                    _LOGGER.info("poll: %s", poll_result)

                    for change in poll_result["result"]["Changes"]:
                        await self._fire_on_component_control_change(change)
                    await asyncio.sleep(1)

            except Exception as e:
                _LOGGER.exception("error during polling: %s", repr(e))
