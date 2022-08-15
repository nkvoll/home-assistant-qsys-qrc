"""Platform for sensor integration."""
from __future__ import annotations

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

from .qsys import core
from .const import DOMAIN


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensor entities."""
    c: core.Core = hass.data[DOMAIN][entry.entry_id]

    entities = dict()

    # TODO: handle entity removal

    entry.async_on_unload(
        asyncio.create_task(keep_polling(hass, entities, c, async_add_entities)).cancel
    )


async def keep_polling(hass, entities, c: core.Core, async_add_entities):
    er = entity_registry.async_get(hass)

    while True:
        try:
            components = await c.component().get_components()

            cg = c.change_group("foo")
            for component in components["result"]:
                controls = await c.component().get_controls(component["Name"])

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
                    entity = ControlSensor(
                        id_for_component_control(component["Name"], control["Name"]),
                        component,
                        control,
                    )

                    # reg_entry_id = er.async_get_entity_id(
                    #    "sensor", DOMAIN, entity.unique_id
                    # )
                    # reg_entry = er.async_get(reg_entry_id)

                    if entity.unique_id not in entities:
                        entities[entity.unique_id] = entity
                        async_add_entities([entity])

            while True:
                poll_result = await cg.poll()
                print("poll", poll_result)

                for change in poll_result["result"]["Changes"]:
                    entity: ControlSensor = entities.get(
                        id_for_component_control(change["Component"], change["Name"])
                    )
                    await entity.on_changed(change)
                await asyncio.sleep(1)

        except Exception as e:
            print("error", e, repr(e))
            import traceback

            traceback.print_exc()


def id_for_component_control(component, control):
    return f"{component}_{control}"


class ControlSensor(SensorEntity):
    _attr_should_poll = False

    camelpattern = re.compile(r"(?<!^)(?=[A-Z])")

    def __init__(self, unique_id, component, control) -> None:
        super().__init__()
        self._attr_unique_id = unique_id
        extra_attrs = {}
        for k, v in control.items():
            extra_attrs[self.camelpattern.sub("_", k).lower()] = v
        self._attr_extra_state_attributes = extra_attrs

    async def on_changed(self, change):
        extra_attrs = {}
        for k, v in change.items():
            extra_attrs[k.lower()] = v
        self._attr_native_value = change["Value"]
        self._attr_extra_state_attributes.update(extra_attrs)
        await self.async_update_ha_state()
