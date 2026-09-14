"""Platform for select integration.

Drives Home Assistant `select` entities from Q-Sys controls that have a
`Choices` list (typical pattern: top-level Named Controls bound to a
multi-state widget). Options can be supplied statically in YAML; if omitted,
they're auto-populated from the QRC `Choices` payload on the first poll.
"""
from __future__ import annotations

import asyncio
import logging

from homeassistant.components.select import SelectEntity
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
    """Set up select entities."""

    core_name = entry.data[CONF_USER_DATA][CONF_CORE_NAME]
    core: qrc.Core = hass.data[DOMAIN].get(CONF_CACHED_CORES, {}).get(core_name)
    if core is None:
        return

    entities = {}

    core_config = config_for_core(hass, core_name)
    poller = changegroup.create_change_group_for_platform(
        core, core_config.get(CONF_CHANGEGROUP), PLATFORM
    )

    for select_config in core_config.get(CONF_PLATFORMS, {}).get(
        CONF_SELECT_PLATFORM, []
    ):
        component_name = select_config.get(CONF_COMPONENT)
        control_name = select_config[CONF_CONTROL]

        ent = QRCSelectEntity(
            hass,
            entry,
            core_name,
            core,
            id_for_component_control(core_name, component_name, control_name),
            select_config.get(CONF_ENTITY_NAME, None),
            component_name,
            control_name,
            select_config.get(CONF_SELECT_OPTIONS, []),
        )

        if ent.unique_id not in entities:
            entities[ent.unique_id] = ent
            async_add_entities([ent])

            poller.subscribe_run_loop_iteration_ending(ent.on_core_polling_ending)
            await poller.subscribe_component_control_changes(
                ent.on_core_change,
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


class QRCSelectEntity(QSysComponentControlBase, SelectEntity):
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
        static_options,
    ) -> None:
        super().__init__(
            hass, config_entry, core_name, core, unique_id, entity_name, component, control
        )
        self._static_options = list(static_options) if static_options else []
        self._attr_options = list(self._static_options)
        self._attr_current_option = None

    async def on_control_changed(self, core, change):
        # If the user pinned options in YAML, keep those; else auto-derive from Choices.
        if not self._static_options:
            choices = change.get("Choices") or []
            if choices:
                self._attr_options = list(choices)

        current = change.get("String")
        if current is not None and self._attr_options and current not in self._attr_options:
            # Edge case: live value is outside the published Choices list — surface it
            # so HA doesn't render an empty selection.
            self._attr_options = list(self._attr_options) + [current]
        self._attr_current_option = current

    async def async_select_option(self, option: str) -> None:
        # Q-Sys multi-state controls accept Value=<index> deterministically.
        # Falling back to {"String": option} works on most Cores but isn't documented;
        # index lookup avoids surprises.
        if option in self._attr_options:
            idx = self._attr_options.index(option)
            await self.update_control({"Value": idx})
        else:
            _LOGGER.warning(
                "select option %r not in current options %s — sending as String fallback",
                option,
                self._attr_options,
            )
            await self.update_control({"String": option})
