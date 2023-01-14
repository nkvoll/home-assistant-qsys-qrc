import re

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity, device_registry

from .const import DOMAIN
from .qsys import qrc


# TODO: consider entity.async_generate_entity_id
def id_for_component_control(core_name, component, control):
    return f"{core_name}_{component}_{control}"


def id_for_component(core_name, component):
    return f"{core_name}_{component}"


_camel_pattern = re.compile(r"(?<!^)(?=[A-Z])")


class QSysComponentBase(entity.Entity):
    _attr_should_poll = False

    def __init__(
            self,
            hass: HomeAssistant,
            core_name: str, core: qrc.Core,
            unique_id: str, entity_name: str,
            component: str
    ) -> None:
        super().__init__()
        self.core = core
        self._attr_unique_id = unique_id
        extra_attrs = {}
        # for k, v in control.items():
        #    extra_attrs[camelpattern.sub("_", k).lower()] = v
        self._attr_extra_state_attributes = extra_attrs

        self.component = component

        core_device_entry = device_registry.async_get(hass).async_get_device({(DOMAIN, core_name)})
        self._attr_device_info = entity.DeviceInfo(
            identifiers=core_device_entry.identifiers,
        )

        self._attr_name = entity_name


class QSysComponentControlBase(QSysComponentBase):
    def __init__(
            self,
            hass: HomeAssistant,
            core_name: str, core: qrc.Core,
            unique_id: str, entity_name: str,
            component: str, control: str
    ) -> None:
        super().__init__(hass, core_name, core, unique_id, entity_name, component)
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
