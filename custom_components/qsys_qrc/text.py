"""Platform for sensor integration."""
from __future__ import annotations

import asyncio

from homeassistant.components.text import (
    TextEntity,
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
    """Set up text entities."""

    # TODO: remove restored entities that are no longer used?
    core: qrc.Core
    for core_name, core in hass.data[DOMAIN].get(CONF_CORES, {}).items():
        entities = {}
        # can platform name be more dynamic than this?
        cg = core.change_group("text_domain")
        poller = changegroup.ChangeGroupPoller(core, cg)

        for text_config in hass.data[DOMAIN] \
                .get(CONF_CONFIG, {}) \
                .get(CONF_CORES, {}) \
                .get(core_name, []) \
                .get(CONF_PLATFORMS, {}) \
                .get(CONF_TEXT_PLATFORM, []):
            component_name = text_config[CONF_COMPONENT]
            control_name = text_config[CONF_CONTROL]

            # need to fetch component and control config first?
            entity = ControlText(
                core,
                text_config[CONF_ENTITY_ID] or id_for_component_control(
                    text_config[CONF_COMPONENT], text_config[CONF_CONTROL],
                ),
                component_name,
                control_name,
            )

            if entity.unique_id not in entities:
                entities[entity.unique_id] = entity
                async_add_entities([entity])

                poller.subscribe_component_control_changes(
                    entity.on_changed, component_name, control_name,
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


class ControlText(QSysSensorBase, TextEntity):
    def __init__(self, core, unique_id, component, control) -> None:
        super().__init__(core, unique_id, component, control)

    async def on_control_changed(self, hub, change):
        self._attr_native_value = change["String"]

    async def async_set_value(self, value: str) -> None:
        """Change the value."""
        await self.update_control({"Value": value})
