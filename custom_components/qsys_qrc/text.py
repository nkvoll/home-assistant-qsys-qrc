"""Platform for text integration."""
from __future__ import annotations

import asyncio
import logging

from homeassistant.components.text import TextEntity
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
    """Set up text entities."""

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

    for text_config in core_config.get(CONF_PLATFORMS, {}).get(CONF_TEXT_PLATFORM, []):
        component_name = text_config[CONF_COMPONENT]
        control_name = text_config[CONF_CONTROL]

        # need to fetch component and control config first?
        control_text_entity = QRCTextEntity(
            hass,
            core_name,
            core,
            id_for_component_control(
                core_name,
                text_config[CONF_COMPONENT],
                text_config[CONF_CONTROL],
            ),
            text_config.get(CONF_ENTITY_NAME, None),
            component_name,
            control_name,
            text_config[CONF_TEXT_MODE],
            text_config[CONF_TEXT_MIN_LENGTH],
            text_config[CONF_TEXT_MAX_LENGTH],
            text_config[CONF_TEXT_PATTERN],
        )

        if control_text_entity.unique_id not in entities:
            entities[control_text_entity.unique_id] = control_text_entity
            async_add_entities([control_text_entity])

            poller.subscribe_run_loop_iteration_ending(
                control_text_entity.on_core_polling_ending
            )
            await poller.subscribe_component_control_changes(
                control_text_entity.on_core_change,
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


class QRCTextEntity(QSysComponentControlBase, TextEntity):
    def __init__(
        self,
        hass,
        core_name,
        core,
        unique_id,
        entity_name,
        component,
        control,
        mode,
        min_length,
        max_length,
        pattern,
    ) -> None:
        super().__init__(
            hass, core_name, core, unique_id, entity_name, component, control
        )

        self._attr_mode = mode
        if min_length is not None:
            self._attr_native_min = min_length
        if max_length is not None:
            self._attr_native_max = max_length
        self._attr_pattern = pattern

    async def on_control_changed(self, core, change):
        self._attr_native_value = change["String"]

    async def async_set_value(self, value: str) -> None:
        """Change the value."""
        await self.update_control({"Value": value})
