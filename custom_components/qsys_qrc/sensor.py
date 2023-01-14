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
from .common import QSysComponentControlBase, id_for_component_control
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
        poller = changegroup.ChangeGroupPoller(core, f"{__name__.rsplit('.', 1)[-1]}_platform")

        for sensor_config in hass.data[DOMAIN] \
                .get(CONF_CONFIG, {}) \
                .get(CONF_CORES, {}) \
                .get(core_name, []) \
                .get(CONF_PLATFORMS, {}) \
                .get(CONF_SENSOR_PLATFORM, []):
            component_name = sensor_config[CONF_COMPONENT]
            control_name = sensor_config[CONF_CONTROL]
            attribute = sensor_config[CONF_SENSOR_ATTRIBUTE]

            # need to fetch component and control config first?
            control_sensor_entity = QRCComponentControlEntity(
                hass,
                core_name,
                core,
                id_for_component_control(
                    core_name, sensor_config[CONF_COMPONENT], sensor_config[CONF_CONTROL],
                ),
                sensor_config.get(CONF_ENTITY_NAME, None),
                component_name,
                control_name,
                attribute
            )

            if control_sensor_entity.unique_id not in entities:
                entities[control_sensor_entity.unique_id] = control_sensor_entity
                async_add_entities([control_sensor_entity])

                await poller.subscribe_component_control_changes(
                    control_sensor_entity.on_core_change, component_name, control_name,
                )

        if len(entities) > 0:
            polling = asyncio.create_task(poller.run_while_core_running())
            entry.async_on_unload(lambda: polling.cancel() and None)


class QRCComponentControlEntity(QSysComponentControlBase, SensorEntity):
    def __init__(self, hass, core_name, core, unique_id, entity_name, component, control, attribute) -> None:
        super().__init__(hass, core_name, core, unique_id, entity_name, component, control)
        self.attribute = attribute

    async def on_control_changed(self, core, change):
        self._attr_native_value = change.get(self.attribute)
