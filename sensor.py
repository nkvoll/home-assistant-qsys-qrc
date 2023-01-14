"""Platform for sensor integration."""
from __future__ import annotations

from homeassistant.components.sensor import (
    SensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .common import QSysSensorBase


async def async_setup_entry(
        hass: HomeAssistant,
        entry: ConfigEntry,
        async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensor entities."""
    # await async_setup_entry_for_type(hass, entry, async_add_entities, lambda com, con: con["Type"] == "Text", ControlSensor)
    pass


class ControlSensor(QSysSensorBase, SensorEntity):
    def __init__(self, unique_id, component, control) -> None:
        super().__init__(unique_id, component, control)
        self._attr_native_value = control["String"]

    async def on_control_changed(self, hub, change):
        self._attr_native_value = change["String"]
