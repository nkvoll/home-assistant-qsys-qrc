"""Platform for switch integration."""
from __future__ import annotations

from homeassistant.components.switch import (
    SwitchEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .common import (QSysSensorBase, async_setup_entry_for_type)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensor entities."""
    await async_setup_entry_for_type(hass, entry, async_add_entities, lambda com, con: con["Type"] == 'Boolean', ControlSwitch)

class ControlSwitch(QSysSensorBase, SwitchEntity):
    def __init__(self, unique_id, component, control) -> None:
        super().__init__(unique_id, component, control)
        self._attr_native_value = control['Value']

    async def on_control_changed(self, hub, change):
        val = change['value']
        if isinstance(val, float):
            val = val == 1.0
        elif isinstance(val, int):
            val = val == 1
        
        if not isinstance(val, bool):
            print('unable to convert change into bool value', change)
            return
        self._attr_is_on = val

    async def async_turn_on(self, **kwargs):
        """Turn the entity on."""
        await self.update_control({'Value', True})

    async def async_turn_off(self, **kwargs):
        """Turn the entity off."""
        await self.update_control({'Value', False})

    async def async_toggle(self, **kwargs):
        """Toggle the entity."""
        await self.update_control({'Value', not self.native_value})