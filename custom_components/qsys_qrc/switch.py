"""Platform for switch integration."""
from __future__ import annotations

import asyncio
import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers import entity_registry as er

from . import changegroup
from .common import QSysComponentControlBase, id_for_component_control, config_for_core
from .const import *
from .qsys import qrc

_LOGGER = logging.getLogger(__name__)
PLATFORM = __name__.rsplit(".", 1)[-1]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up switch entities."""

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

    for switch_config in core_config.get(CONF_PLATFORMS, {}).get(
        CONF_SWITCH_PLATFORM, []
    ):
        component_name = switch_config[CONF_COMPONENT]
        control_name = switch_config[CONF_CONTROL]

        # need to fetch component and control config first?
        control_switch_entity = QRCSwitchEntity(
            hass,
            core_name,
            core,
            id_for_component_control(
                core_name,
                switch_config[CONF_COMPONENT],
                switch_config[CONF_CONTROL],
            ),
            switch_config.get(CONF_ENTITY_NAME, None),
            component_name,
            control_name,
            switch_config[CONF_DEVICE_CLASS],
        )

        if control_switch_entity.unique_id not in entities:
            entities[control_switch_entity.unique_id] = control_switch_entity
            async_add_entities([control_switch_entity])

            poller.subscribe_run_loop_iteration_ending(
                control_switch_entity.on_core_polling_ending
            )
            await poller.subscribe_component_control_changes(
                control_switch_entity.on_core_change,
                component_name,
                control_name,
            )

    if len(entities) > 0:
        polling = asyncio.create_task(poller.run_while_core_running())
        entry.async_on_unload(lambda: polling.cancel() and None)

    for entity_entry in er.async_entries_for_config_entry(
        er.async_get(hass), entry.entry_id
    ):
        if entity_entry.domain != PLATFORM:
            continue
        if not entities.get(entity_entry.unique_id):
            _LOGGER.debug("Removing old entity: %s", entity_entry.entity_id)
            er.async_get(hass).async_remove(entity_entry.entity_id)


class QRCSwitchEntity(QSysComponentControlBase, SwitchEntity):
    def __init__(
        self,
        hass,
        core_name,
        core,
        unique_id,
        entity_name,
        component,
        control,
        device_class,
    ) -> None:
        super().__init__(
            hass, core_name, core, unique_id, entity_name, component, control
        )

        self._attr_device_class = device_class

    async def on_control_changed(self, core, change):
        val = change["Value"]
        if isinstance(val, float):
            val = val == 1.0
        elif isinstance(val, int):
            val = val == 1

        if not isinstance(val, bool):
            _LOGGER.warning("Unable to convert change into bool value: %s", change)
            return
        self._attr_is_on = val

    async def async_turn_on(self, **kwargs):
        """Turn the entity on."""
        await self.update_control({"Value": True})

    async def async_turn_off(self, **kwargs):
        """Turn the entity off."""
        await self.update_control({"Value": False})

    async def async_toggle(self, **kwargs):
        """Toggle the entity."""
        await self.update_control({"Value": not self.is_on})
