import re
import asyncio
from wsgiref.handlers import CGIHandler

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import TEMP_CELSIUS
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers import entity_registry
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from .hub import Hub
from .const import DOMAIN


def id_for_component_control(component, control):
    return f"{component}_{control}"

camelpattern = re.compile(r"(?<!^)(?=[A-Z])")

class QSysSensorBase:
    _attr_should_poll = False

    def __init__(self, hub: Hub, unique_id, component, control) -> None:
        super().__init__()
        self.hub = hub
        self._attr_unique_id = unique_id
        extra_attrs = {}
        for k, v in control.items():
            extra_attrs[self.camelpattern.sub("_", k).lower()] = v
        self._attr_extra_state_attributes = extra_attrs

    async def on_changed(self, hub, change):
        extra_attrs = {}
        for k, v in change.items():
            extra_attrs[k.lower()] = v
        self._attr_extra_state_attributes.update(extra_attrs)

        await self.on_control_changed(hub, change)
        await self.async_update_ha_state()

    async def on_control_changed(self, change):
        pass

    async def update_control(self, control_values):
        payload = {'Name': self.control['Name']}
        payload.update(control_values)
        await self.hub.core.component.set(self.component['Name'], controls=[
            payload
        ])

async def async_setup_entry_for_type(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
    control_filter,
    entity_factory
) -> None:
    """Set up sensor entities."""
    hub: Hub = hass.data[DOMAIN][entry.entry_id]

    entities = dict()

    # TODO: handle entity removal

    def add_component_control(hub: Hub, component, control):
        entity = entity_factory(
            hub,
            id_for_component_control(component["Name"], control["Name"]),
            component,
            control,
        )

        if entity.unique_id not in entities:
            entities[entity.unique_id] = entity
            async_add_entities([entity])

            hub.subscribe_component_control_changes(
                entity.on_changed, component["Name"], control["Name"]
            )

    # TODO: unsubscribe
    hub.subscribe_component_control(
        add_component_control, control_filter
    )