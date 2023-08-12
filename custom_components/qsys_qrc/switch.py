"""Platform for switch integration."""
from __future__ import annotations

import asyncio
import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import changegroup
from .common import QSysComponentControlBase, id_for_component_control
from .const import *
from .qsys import qrc

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up switch entities."""

    # TODO: remove restored entities that are no longer used?
    core_name = entry.data[CONF_USER_DATA][CONF_CORE_NAME]
    core: qrc.Core = hass.data[DOMAIN].get(CONF_CORES, {}).get(core_name)
    if core is None:
        return

    entities = {}
    poller = changegroup.ChangeGroupPoller(
        core, f"{__name__.rsplit('.', 1)[-1]}_platform"
    )

    for switch_config in (
        hass.data[DOMAIN]
        .get(CONF_CONFIG, {})
        .get(CONF_CORES, {})
        .get(core_name, {})
        .get(CONF_PLATFORMS, {})
        .get(CONF_SWITCH_PLATFORM, [])
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

        def on_unload():
            polling.cancel()

        entry.async_on_unload(on_unload)


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
