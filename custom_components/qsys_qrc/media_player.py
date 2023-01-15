"""Platform for media_player integration."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.components import media_source
from homeassistant.components.media_player import (
    BrowseMedia, MediaPlayerEnqueue, MediaPlayerEntity,
    MediaPlayerEntityFeature, MediaPlayerState, MediaType,
    async_process_play_media_url)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import PlatformNotReady
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util.dt import utcnow

from . import changegroup
from .common import QSysComponentBase, id_for_component
from .const import *
from .qsys import qrc

_LOGGER = logging.getLogger(__name__)

position_0db = 0.83333331


async def async_setup_entry(
        hass: HomeAssistant,
        entry: ConfigEntry,
        async_add_entities: AddEntitiesCallback,
) -> None:
    try:
        await async_setup_entry_safe(hass, entry, async_add_entities)
    except asyncio.TimeoutError as te:
        raise PlatformNotReady("timeouterror during setup") from te


async def async_setup_entry_safe(
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
                media_player_entity = QRCUrlReceiverEntity(
                    hass,
                    core_name,
                    core,
                    id_for_component(
                        core_name, media_player_config[CONF_COMPONENT]
                    ),
                    media_player_config.get(CONF_ENTITY_NAME, None),
                    component_name,
                    media_player_config[CONF_DEVICE_CLASS],
                )
            elif component_type == "audio_file_player":
                media_player_entity = QRCAudioFilePlayerEntity(
                    hass,
                    core_name,
                    core,
                    id_for_component(
                        core_name, media_player_config[CONF_COMPONENT]
                    ),
                    media_player_config.get(CONF_ENTITY_NAME, None),
                    component_name,
                    media_player_config[CONF_DEVICE_CLASS],
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
                    poller.subscribe_run_loop_iteration_ending(media_player_entity.on_core_polling_ending)
                    await poller.subscribe_component_control_changes(
                        media_player_entity.on_changed, component_name, control["Name"],
                    )

        if len(entities) > 0:
            # TODO: handle poll exceptions, disconnections and re-connections
            polling = asyncio.create_task(poller.run_while_core_running())

            def on_unload():
                polling.cancel()

            entry.async_on_unload(on_unload)


class QRCUrlReceiverEntity(QSysComponentBase, MediaPlayerEntity):
    _attr_supported_features = (
            MediaPlayerEntityFeature(0)
            | MediaPlayerEntityFeature.VOLUME_SET
            | MediaPlayerEntityFeature.VOLUME_MUTE
            | MediaPlayerEntityFeature.PLAY_MEDIA
            # | MediaPlayerEntityFeature.PLAY
            # | MediaPlayerEntityFeature.STOP
            | MediaPlayerEntityFeature.TURN_ON
            | MediaPlayerEntityFeature.TURN_OFF
            # | MediaPlayerEntityFeature.SELECT_SOURCE
            # | MediaPlayerEntityFeature.SELECT_SOUND_MODE
            | MediaPlayerEntityFeature.BROWSE_MEDIA
    )

    def __init__(self, hass, core_name, core, unique_id, entity_name, component, device_class) -> None:
        super().__init__(hass, core_name, core, unique_id, entity_name, component)

        self._attr_device_class = device_class

        self._qsys_state = {}

    async def on_changed(self, core, change):
        _LOGGER.debug("media player control %s changed: %s", self.unique_id, change)

        self._attr_available = True

        name = change["Name"]
        value = change["Value"]

        self._qsys_state[name] = change

        if name == "enable":
            self._update_state()

        elif name == "status":
            self._update_state()

        elif name == "track.name":
            self._attr_media_title = value

        elif name == "channel.1.gain" or name == "channel.2.gain":
            self._attr_volume_level = max(0.0, min(1.0, change["Position"] / position_0db))

        elif name == "channel.1.mute" or name == "channel.2.mute":
            self._attr_is_volume_muted = value == 1.0

        await self.async_update_ha_state()

    def _update_state(self):
        enabled = self._qsys_state.get("enable", {}).get("Value", None) == 1.0
        if not enabled:
            self._attr_state = MediaPlayerState.OFF
            return

        status_to_state = {
            "OK": MediaPlayerState.PLAYING,
            "Compromised": MediaPlayerState.PLAYING,
            "Fault": MediaPlayerState.IDLE,
            "Initializing": MediaPlayerState.BUFFERING,
            "Not Present": MediaPlayerState.IDLE,
            "Missing": MediaPlayerState.IDLE,
        }

        self._attr_state = status_to_state.get(
            self._qsys_state.get("status", {}).get("Value", None), MediaPlayerState.ON
        )

    async def async_turn_on(self) -> None:
        await self.core.component().set(self.component, [{"Name": "enable", "Value": 1.0}])

    async def async_turn_off(self) -> None:
        await self.core.component().set(self.component, [{"Name": "enable", "Value": 0.0}])

    async def async_mute_volume(self, mute: bool) -> None:
        await self.core.component().set(self.component, [
            {"Name": "channel.1.mute", "Value": 1.0 if mute else 0.0},
            {"Name": "channel.2.mute", "Value": 1.0 if mute else 0.0},
        ])

    async def async_set_volume_level(self, volume: float) -> None:
        await self.core.component().set(self.component, [
            {"Name": "channel.1.gain", "Position": volume * position_0db},
            {"Name": "channel.2.gain", "Position": volume * position_0db},
        ])

    async def async_browse_media(
            self, media_content_type: str | None = None, media_content_id: str | None = None
    ) -> BrowseMedia:
        """Implement the websocket media browsing helper."""
        # If your media player has no own media sources to browse, route all browse commands
        # to the media source integration.
        return await media_source.async_browse_media(
            self.hass,
            media_content_id,
            # This allows filtering content. In this case it will only show audio sources.
            content_filter=lambda item: item.media_content_type.startswith("audio/"),
        )

    async def async_play_media(
            self,
            media_type: str,
            media_id: str,
            enqueue: MediaPlayerEnqueue | None = None,
            announce: bool | None = None, **kwargs: Any
    ) -> None:
        """Play a piece of media."""
        if media_source.is_media_source_id(media_id):
            media_type = MediaType.MUSIC
            play_item = await media_source.async_resolve_media(self.hass, media_id, self.entity_id)
            # play_item returns a relative URL if it has to be resolved on the Home Assistant host
            # This call will turn it into a full URL
            media_id = async_process_play_media_url(self.hass, play_item.url)

        await self.core.component().set(self.component, [{"Name": "url", "Value": media_id}])


class QRCAudioFilePlayerEntity(QSysComponentBase, MediaPlayerEntity):
    _attr_supported_features = (
            MediaPlayerEntityFeature(0)
            | MediaPlayerEntityFeature.VOLUME_SET
            | MediaPlayerEntityFeature.VOLUME_MUTE
            | MediaPlayerEntityFeature.PLAY_MEDIA
            | MediaPlayerEntityFeature.PLAY
            | MediaPlayerEntityFeature.STOP
            | MediaPlayerEntityFeature.SEEK
            # | MediaPlayerEntityFeature.SELECT_SOURCE
            # | MediaPlayerEntityFeature.SELECT_SOUND_MODE
            | MediaPlayerEntityFeature.BROWSE_MEDIA
    )

    def __init__(self, hass, core_name, core, unique_id, entity_name, component, device_class) -> None:
        super().__init__(hass, core_name, core, unique_id, entity_name, component)

        self._attr_device_class = device_class

        self._qsys_state = {}

    async def on_changed(self, core, change):
        _LOGGER.warning("media player control %s changed: %s", self.unique_id, change)

        self._attr_available = True

        name = change["Name"]
        value = change["Value"]

        self._qsys_state[name] = change

        if name == "enable":
            self._update_state()
            _LOGGER.info("Status updated: %s", change)

        elif name == "status":
            self._update_state()

        elif name == "track.name":
            self._attr_media_title = value

        elif name == "gain":
            self._attr_volume_level = max(0.0, min(1.0, change["Position"] / position_0db))

        elif name == "mute" or name == "mute":
            self._attr_is_volume_muted = value == 1.0

        elif name == "progress":
            # TODO: does this need to update / be invalidated with playing states?
            self._attr_media_position = change["Position"]
            self._attr_media_position_updated_at = utcnow()

        await self.async_update_ha_state()

    # browsing bits
    # {'Component': 'audio_player_doorbell_main', 'Name': 'directory', 'String': '', 'Value': 0.0, 'Position': 0.0, 'Choices': [], 'Color': ''}
    # {'Component': 'audio_player_doorbell_main', 'Name': 'directory.ui', 'String': '', 'Value': 0.0, 'Position': 0.0, 'Choices': [], 'Color': '', 'Disabled': True}
    # {'Component': 'audio_player_doorbell_main', 'Name': 'filename', 'String': '', 'Value': 0.0, 'Position': 0.0, 'Choices': [], 'Color': ''}
    # {'Component': 'audio_player_doorbell_main', 'Name': 'filename.ui', 'String': '', 'Value': 0.0, 'Position': 0.0, 'Choices': [], 'Color': '', 'Disabled': True}
    # {'Component': 'audio_player_doorbell_main', 'Name': 'root', 'String': 'Audio/', 'Value': 0.0, 'Position': 0.0, 'Choices': [], 'Color': ''}
    # {'Component': 'audio_player_doorbell_main', 'Name': 'root.ui', 'String': 'Audio/', 'Value': 0.0, 'Position': 0.0, 'Choices': [], 'Color': '', 'Disabled': True}

    def _update_state(self):
        if self._qsys_state.get("playing", {}).get("Value", 0.0) == 1.0:
            self._attr_state = MediaPlayerState.PLAYING
        elif self._qsys_state.get("paused", {}).get("Value", 0.0) == 1.0:
            self._attr_state = MediaPlayerState.PAUSED
        elif self._qsys_state.get("stopped", {}).get("Value", 0.0) == 1.0:
            self._attr_state = MediaPlayerState.IDLE
        else:
            # TODO: include "status" field values?
            self._attr_state = MediaPlayerState.ON
            return

    async def async_media_play(self) -> None:
        await self.core.component().set(self.component, [{"Name": "play.state.trigger", "Value": 1.0}])

    async def async_media_pause(self) -> None:
        await self.core.component().set(self.component, [{"Name": "pause.state.trigger", "Value": 1.0}])

    async def async_media_stop(self) -> None:
        await self.core.component().set(self.component, [{"Name": "stop.state.trigger", "Value": 1.0}])

    async def async_media_seek(self, position: float) -> None:
        # TODO: position? range of this + actual control to use is unclear, could be progress/remaining?
        await self.core.component().set(self.component, [{"Name": "locate", "Position": position}])

    async def async_mute_volume(self, mute: bool) -> None:
        await self.core.component().set(self.component, [
            {"Name": "mute", "Value": 1.0 if mute else 0.0},
        ])

    async def async_set_volume_level(self, volume: float) -> None:
        await self.core.component().set(self.component, [
            {"Name": "gain", "Position": volume * position_0db},
        ])

    async def async_browse_media(
            self, media_content_type: str | None = None, media_content_id: str | None = None
    ) -> BrowseMedia:
        """Implement the websocket media browsing helper."""
        _LOGGER.warning(
            "UNSUPPORTED / UNTESTED: browse_media: media_content_type:%s, media_content_id:%s",
            media_content_type, media_content_id,
        )

        # If your media player has no own media sources to browse, route all browse commands
        # to the media source integration.
        return await media_source.async_browse_media(
            self.hass,
            media_content_id,
            # This allows filtering content. In this case it will only show audio sources.
            content_filter=lambda item: item.media_content_type.startswith("audio/"),
        )

    async def async_play_media(
            self,
            media_type: str,
            media_id: str,
            enqueue: MediaPlayerEnqueue | None = None,
            announce: bool | None = None, **kwargs: Any
    ) -> None:
        """Play a piece of media."""

        _LOGGER.warning("UNSUPPORTED / UNTESTED: play_media: media_type:%s, media_id:%s", media_type, media_id)

        if media_source.is_media_source_id(media_id):
            media_type = MediaType.MUSIC
            play_item = await media_source.async_resolve_media(self.hass, media_id, self.entity_id)
            # play_item returns a relative URL if it has to be resolved on the Home Assistant host
            # This call will turn it into a full URL
            media_id = async_process_play_media_url(self.hass, play_item.url)

        directory, filename = media_id.rsplit("/", 1)

        await self.core.component().set(self.component, [
            {"Name": "directory", "Value": directory},
            {"Name": "filename", "Value": filename},
            {"Name": "play.state.trigger", "Value": 1.0}
        ])
