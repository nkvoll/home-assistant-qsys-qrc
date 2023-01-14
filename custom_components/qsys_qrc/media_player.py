"""Platform for media_player integration."""
from __future__ import annotations

import asyncio
import logging

from homeassistant.components.sensor import (
    SensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import PlatformNotReady
from homeassistant.helpers import entity, device_registry
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import changegroup
from .common import QSysComponentBase, id_for_component
from .const import *
from .qsys import qrc

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
        hass: HomeAssistant,
        entry: ConfigEntry,
        async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up media player entities."""

    # TODO: remove restored entities that are no longer used?
    core: qrc.Core
    for core_name, core in hass.data[DOMAIN].get(CONF_CORES, {}).items():
        entities = {}
        # can platform name be more dynamic than this?
        poller = changegroup.ChangeGroupPoller(core, f"{__name__.rsplit('.', 1)[-1]}_platform")

        # TODO: this is a little hard to reload at the moment, do via listener instead?
        # TODO: timeouts for remote calls like these?
        components = await core.component().get_components()
        component_by_name = {}
        for component in components["result"]:
            component_by_name[component["Name"]] = component

        for media_player_config in hass.data[DOMAIN] \
                .get(CONF_CONFIG, {}) \
                .get(CONF_CORES, {}) \
                .get(core_name, []) \
                .get(CONF_PLATFORMS, {}) \
                .get(CONF_MEDIA_PLAYER_PLATFORM, []):
            component_name = media_player_config[CONF_COMPONENT]

            component = component_by_name.get(component_name)

            media_player_entity = None
            component_type = component["Type"]
            if component_type == "URL_receiver":
                media_player_entity = QRCMediaPlayerEntity(
                    hass,
                    core_name,
                    core,
                    id_for_component(
                        core_name, media_player_config[CONF_COMPONENT]
                    ),
                    media_player_config.get(CONF_ENTITY_NAME, None),
                    component_name,
                )
            else:
                msg = f"Component has invalid type for media player: {component_type}"
                _LOGGER.warning(msg)
                raise PlatformNotReady(msg)

            if media_player_entity.unique_id not in entities:
                entities[media_player_entity.unique_id] = media_player_entity
                async_add_entities([media_player_entity])

                get_controls_result = await core.component().get_controls(component_name)

                for control in get_controls_result["result"]["Controls"]:
                    await poller.subscribe_component_control_changes(
                        media_player_entity.on_changed, component_name, control["Name"],
                    )

        if len(entities) > 0:
            # TODO: handle poll exceptions, disconnections and re-connections
            polling = asyncio.create_task(poller.run_while_core_running())
            entry.async_on_unload(lambda: polling.cancel() and None)


class QRCMediaPlayerEntity(QSysComponentBase, SensorEntity):
    def __init__(self, hass, core_name, core, unique_id, entity_name, component) -> None:
        super().__init__(hass, core_name, core, unique_id, entity_name, component)

    async def on_changed(self, core, change):
        #self._attr_native_value = change.get(self.attribute)
        _LOGGER.warning("media player control changed: %s", change)
