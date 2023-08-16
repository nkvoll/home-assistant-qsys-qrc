"""Platform for sensor integration."""
from __future__ import annotations

import asyncio
import logging

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers import entity_registry as er

from . import changegroup
from .common import (
    QSysComponentBase,
    QSysComponentControlBase,
    id_for_component_control,
    config_for_core,
)
from .const import *
from .qsys import qrc

_LOGGER = logging.getLogger(__name__)
PLATFORM = __name__.rsplit(".", 1)[-1]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensor entities."""

    # TODO: remove restored entities that are no longer used?
    core_name = entry.data[CONF_USER_DATA][CONF_CORE_NAME]
    core: qrc.Core = hass.data[DOMAIN].get(CONF_CACHED_CORES, {}).get(core_name)
    if core is None:
        return

    entities = {}

    core_config = config_for_core(hass, core_name)
    # can platform name be more dynamic than this?
    poller = changegroup.create_change_group_for_platform(
        core, core_config.get(CONF_CHANGEGROUP), PLATFORM
    )

    for sensor_config in core_config.get(CONF_PLATFORMS, {}).get(
        CONF_SENSOR_PLATFORM, []
    ):
        component_name = sensor_config[CONF_COMPONENT]
        control_name = sensor_config[CONF_CONTROL]
        attribute = sensor_config[CONF_SENSOR_ATTRIBUTE]

        # need to fetch component and control config first?
        control_sensor_entity = QRCComponentControlEntity(
            hass,
            core_name,
            core,
            id_for_component_control(
                core_name,
                sensor_config[CONF_COMPONENT],
                sensor_config[CONF_CONTROL],
            ),
            sensor_config.get(CONF_ENTITY_NAME, None),
            component_name,
            control_name,
            attribute,
            sensor_config[CONF_DEVICE_CLASS],
            sensor_config[CONF_UNIT_OF_MEASUREMENT],
            sensor_config[CONF_STATE_CLASS],
        )

        if control_sensor_entity.unique_id not in entities:
            entities[control_sensor_entity.unique_id] = control_sensor_entity
            async_add_entities([control_sensor_entity])

            poller.subscribe_run_loop_iteration_ending(
                control_sensor_entity.on_core_polling_ending
            )
            await poller.subscribe_component_control_changes(
                control_sensor_entity.on_core_change,
                component_name,
                control_name,
            )

    if len(entities) > 0:
        polling = asyncio.create_task(poller.run_while_core_running())

        def on_unload():
            polling.cancel()

        entry.async_on_unload(on_unload)

    engine_status_sensor = EngineStatusEntity(
        hass,
        core_name,
        core,
        f"{core_name}_engine",
        f"{core_name}_engine",
        f"{core_name}_engine_component",  # unused
    )
    async_add_entities([engine_status_sensor])

    async def update():
        cancelled = False
        while not cancelled:
            try:
                status = await core.status_get()

                engine_status_sensor.set_available(True)
                engine_status_sensor.set_attr_native_value(
                    status.get("result", {}).get("Status", {}).get("Code", -1)
                )
                engine_status_sensor.set_attr_extra_state_attributes(
                    status.get("result", {})
                )
                engine_status_sensor.async_write_ha_state()
            except asyncio.CancelledError:
                cancelled = True

            except Exception:
                pass

            finally:
                engine_status_sensor.set_available(False)
                engine_status_sensor.async_write_ha_state()
                if not cancelled:
                    await asyncio.sleep(5)

    entities[engine_status_sensor.unique_id] = engine_status_sensor
    updater = asyncio.create_task(update())

    def on_unload():
        updater.cancel()

    entry.async_on_unload(on_unload)

    for entity_entry in er.async_entries_for_config_entry(
        er.async_get(hass), entry.entry_id
    ):
        if entity_entry.domain != PLATFORM:
            continue
        if not entities.get(entity_entry.unique_id):
            _LOGGER.debug("Removing old entity: %s", entity_entry.entity_id)
            er.async_get(hass).async_remove(entity_entry.entity_id)


class EngineStatusEntity(QSysComponentBase, SensorEntity):
    def set_available(self, available):
        self._attr_available = available

    def set_attr_native_value(self, value):
        self._attr_native_value = value

    def set_attr_extra_state_attributes(self, value):
        self._attr_extra_state_attributes = value


class QRCComponentControlEntity(QSysComponentControlBase, SensorEntity):
    def __init__(
        self,
        hass,
        core_name,
        core,
        unique_id,
        entity_name,
        component,
        control,
        attribute,
        device_class,
        unit_of_measurement,
        state_class,
    ) -> None:
        super().__init__(
            hass, core_name, core, unique_id, entity_name, component, control
        )
        self.attribute = attribute

        self._attr_device_class = device_class
        self._attr_native_unit_of_measurement = unit_of_measurement
        self._attr_state_class = state_class

    async def on_control_changed(self, core, change):
        # TODO: if change["Choices"], copy to attr options?
        self._attr_native_value = change.get(self.attribute)
