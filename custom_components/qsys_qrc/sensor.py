"""Platform for sensor integration."""
from __future__ import annotations

import asyncio

from homeassistant.components.sensor import (
    SensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import changegroup
from .common import QSysSensorBase, id_for_component_control
from .const import *
from .qsys import qrc


async def async_setup_entry(
        hass: HomeAssistant,
        entry: ConfigEntry,
        async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensor entities."""

    # TODO: remove restored entities that are no longer used?
    core: qrc.Core
    for core_name, core in hass.data[DOMAIN].get(CONF_CORES, {}).items():
        entities = {}
        # can platform name be more dynamic than this?
        cg = core.change_group("sensor_domain")
        poller = changegroup.ChangeGroupPoller(core, cg)

        for sensor_config in hass.data[DOMAIN] \
                .get(CONF_CONFIG, {}) \
                .get(CONF_CORES, {}) \
                .get(core_name, []) \
                .get(CONF_PLATFORMS, {}) \
                .get(CONF_SENSOR_PLATFORM, []):
            component_name = sensor_config[CONF_COMPONENT]
            control_name = sensor_config[CONF_CONTROL]

            # need to fetch component and control config first?
            control_sensor_entity = ControlSensor(
                core,
                sensor_config[CONF_ENTITY_ID] or id_for_component_control(
                    sensor_config[CONF_COMPONENT], sensor_config[CONF_CONTROL],
                ),
                component_name,
                control_name,
                )

            if control_sensor_entity.unique_id not in entities:
                entities[control_sensor_entity.unique_id] = control_sensor_entity
                async_add_entities([control_sensor_entity])

                poller.subscribe_component_control_changes(
                    control_sensor_entity.on_changed, component_name, control_name,
                )

            await cg.add_component_control({
                "Name": component_name,
                "Controls": [
                    {"Name": control_name}
                ],
            })

        if len(entities) > 0:
            polling = asyncio.create_task(poller.run_poll())
            entry.async_on_unload(lambda: polling.cancel() and None)


class ControlSensor(QSysSensorBase, SensorEntity):
    def __init__(self, core, unique_id, component, control) -> None:
        super().__init__(core, unique_id, component, control)

    async def on_control_changed(self, hub, change):
        self._attr_native_value = change["String"]

    async def async_set_value(self, value: str) -> None:
        """Change the value."""
        await self.update_control({"Value": value})
