"""Platform for binary sensor integration."""

from __future__ import annotations

import logging

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers import entity_registry as er

from .common import (
    QSysComponentControlBase,
    id_for_component_control,
    config_for_core,
    poller_for_entry,
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
    """Set up binary sensor entities."""

    # TODO: remove restored entities that are no longer used?
    core_name = entry.data[CONF_USER_DATA][CONF_CORE_NAME]
    core: qrc.Core = hass.data[DOMAIN].get(CONF_CACHED_CORES, {}).get(core_name)
    if core is None:
        return

    entities = {}

    core_config = config_for_core(hass, entry)
    # can platform name be more dynamic than this?
    poller = poller_for_entry(hass, entry)

    for binary_sensor_config in core_config.get(CONF_PLATFORMS, {}).get(
        CONF_BINARY_SENSOR_PLATFORM, []
    ):
        component_name = binary_sensor_config[CONF_COMPONENT]
        control_name = binary_sensor_config[CONF_CONTROL]

        # need to fetch component and control config first?
        binary_sensor_entity = QRCBinarySensorEntity(
            hass,
            entry,
            core_name,
            core,
            id_for_component_control(
                core_name,
                binary_sensor_config[CONF_COMPONENT],
                binary_sensor_config[CONF_CONTROL],
            ),
            binary_sensor_config.get(CONF_ENTITY_NAME, None),
            component_name,
            control_name,
            binary_sensor_config[CONF_DEVICE_CLASS],
        )

        if binary_sensor_entity.unique_id not in entities:
            entities[binary_sensor_entity.unique_id] = binary_sensor_entity
            async_add_entities([binary_sensor_entity])

            poller.subscribe_run_loop_iteration_ending(
                binary_sensor_entity.on_core_polling_ending
            )
            await poller.subscribe_component_control_changes(
                binary_sensor_entity.on_core_change,
                component_name,
                control_name,
            )

    for entity_entry in er.async_entries_for_config_entry(
        er.async_get(hass), entry.entry_id
    ):
        if entity_entry.domain != PLATFORM:
            continue
        if not entities.get(entity_entry.unique_id):
            _LOGGER.debug("Removing old entity: %s", entity_entry.entity_id)
            er.async_get(hass).async_remove(entity_entry.entity_id)


class QRCBinarySensorEntity(QSysComponentControlBase, BinarySensorEntity):
    def __init__(
        self,
        hass,
        config_entry: ConfigEntry,
        core_name,
        core,
        unique_id,
        entity_name,
        component,
        control,
        device_class,
    ) -> None:
        super().__init__(
            hass,
            config_entry,
            core_name,
            core,
            unique_id,
            entity_name,
            component,
            control,
        )

        self._attr_device_class = device_class

    async def on_control_changed(self, core, change):
        """Expose Boolean or numeric 0/1 values without control writes."""
        value = change.get("Value")
        if isinstance(value, bool):
            self._attr_is_on = value
        elif isinstance(value, (int, float)) and value in (0, 1):
            self._attr_is_on = bool(value)
        else:
            self._attr_is_on = None
            _LOGGER.warning(
                "Binary sensor received a value that is not Boolean or numeric 0/1"
            )
