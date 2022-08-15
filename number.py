"""Platform for number integration."""
from __future__ import annotations

from homeassistant.components.number import (
    NumberEntity,
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
    await async_setup_entry_for_type(hass, entry, async_add_entities, lambda com, con: con["Type"] == 'Float', ControlNumber)

class ControlNumber(QSysSensorBase, NumberEntity):
    def __init__(self, unique_id, component, control) -> None:
        super().__init__(unique_id, component, control)
        self._attr_native_min_value = control['ValueMin']
        self._attr_native_max_value = control['ValueMax']
        self._attr_native_step = 0.1
        self._attr_native_value = control['Value']

    async def on_control_changed(self, hub, change):
        self._attr_native_value = change["Value"]

    async def async_set_native_value(self, value: float) -> None:
        """Update the current value."""
        await self.update_control({'Value', value})
