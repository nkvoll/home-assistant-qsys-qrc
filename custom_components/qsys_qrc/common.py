import re

from homeassistant.helpers import entity

from .qsys import qrc
from .const import DOMAIN


# TODO: consider entity.async_generate_entity_id
def id_for_component_control(component, control):
    return f"{DOMAIN}_{component}_{control}"


def id_for_component(component):
    return f"{DOMAIN}_{component}"


_camel_pattern = re.compile(r"(?<!^)(?=[A-Z])")


class QSysComponentBase(entity.Entity):
    _attr_should_poll = False

    def __init__(self, core: qrc.Core, unique_id, component) -> None:
        super().__init__()
        self.core = core
        self._attr_unique_id = unique_id
        extra_attrs = {}
        # for k, v in control.items():
        #    extra_attrs[camelpattern.sub("_", k).lower()] = v
        self._attr_extra_state_attributes = extra_attrs

        self.component = component


class QSysComponentControlBase(QSysComponentBase):
    def __init__(self, core: qrc.Core, unique_id, component, control) -> None:
        super().__init__(core, unique_id, component)
        self.control = control

    async def on_core_change(self, core, change):
        extra_attrs = {}
        for k, v in change.items():
            extra_attrs[_camel_pattern.sub("_", k).lower()] = v
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
