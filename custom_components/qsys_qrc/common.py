import re

from homeassistant.helpers import entity

from .qsys import qrc


# TODO: consider entity.async_generate_entity_id
def id_for_component_control(component, control):
    return f"{component}_{control}"


camelpattern = re.compile(r"(?<!^)(?=[A-Z])")


class QSysSensorBase(entity.Entity):
    _attr_should_poll = False

    def __init__(self, core: qrc.Core, unique_id, component, control) -> None:
        super().__init__()
        self.core = core
        self._attr_unique_id = unique_id
        extra_attrs = {}
        # for k, v in control.items():
        #    extra_attrs[camelpattern.sub("_", k).lower()] = v
        self._attr_extra_state_attributes = extra_attrs

        self.component = component
        self.control = control

    async def on_changed(self, core, change):
        extra_attrs = {}
        for k, v in change.items():
            extra_attrs[camelpattern.sub("_", k).lower()] = v
        self._attr_extra_state_attributes.update(extra_attrs)

        await self.on_control_changed(core, change)
        await self.async_update_ha_state()

    async def on_control_changed(self, core, change):
        pass

    async def update_control(self, control_values):
        payload = {"Name": self.control}
        payload.update(**control_values)
        await self.core.component().set(self.component, controls=[
            payload
        ])
