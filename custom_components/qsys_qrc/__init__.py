"""The Q-Sys QRC integration."""
from __future__ import annotations

import asyncio
import logging

import voluptuous as vol
from homeassistant.components import media_player, number, sensor, switch, text
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.typing import ConfigType

from .const import *
from .qsys import qrc

PLATFORMS: list[Platform] = [Platform.NUMBER, Platform.SENSOR, Platform.SWITCH, Platform.TEXT, Platform.MEDIA_PLAYER]

_LOGGER = logging.getLogger(__name__)

devices = {}

CONFIG_SCHEMA = vol.Schema({
    DOMAIN: vol.Schema({
        CONF_CORES: vol.Schema(
            {
                vol.basestring: vol.Schema({
                    vol.Optional(CONF_PLATFORMS): vol.Schema({
                        CONF_MEDIA_PLAYER_PLATFORM: vol.Schema([
                            vol.Schema({
                                vol.Optional(CONF_ENTITY_NAME, default=None): vol.Any(None, str),
                                vol.Optional(CONF_DEVICE_CLASS, default=None,):
                                    vol.Any(None, media_player.MediaPlayerDeviceClass),
                                vol.Required(CONF_COMPONENT): str,
                            })
                        ]),
                        CONF_NUMBER_PLATFORM: vol.Schema([
                            vol.Schema({
                                vol.Optional(CONF_ENTITY_NAME, default=None): vol.Any(None, str),
                                vol.Optional(CONF_DEVICE_CLASS, default=None):
                                    vol.Any(None, number.DEVICE_CLASSES_SCHEMA),
                                vol.Optional(CONF_UNIT_OF_MEASUREMENT, default=None): vol.Any(None, str),
                                vol.Required(CONF_COMPONENT): str,
                                vol.Required(CONF_CONTROL): str,
                                vol.Optional(CONF_NUMBER_USE_POSITION, default=False): bool,
                                vol.Optional(CONF_NUMBER_MIN_VALUE, default=0.0): vol.Coerce(float),
                                vol.Optional(CONF_NUMBER_MAX_VALUE, default=100.0): vol.Coerce(float),
                                vol.Optional(CONF_NUMBER_POSITION_UPPER_LIMIT, default=1.0): vol.Coerce(float),
                                vol.Optional(CONF_NUMBER_STEP, default=1.0): vol.Coerce(float),
                                vol.Optional(CONF_NUMBER_MODE, default=number.NumberMode.AUTO): vol.Coerce(
                                    number.NumberMode),
                                vol.Optional(CONF_NUMBER_CHANGE_TEMPLATE, default=None): vol.Any(None, str),
                                vol.Optional(CONF_NUMBER_VALUE_TEMPLATE, default=None): vol.Any(None, str),
                            })
                        ]),
                        CONF_SENSOR_PLATFORM: vol.Schema([
                            vol.Schema({
                                vol.Optional(CONF_ENTITY_NAME, default=None): vol.Any(None, str),
                                vol.Optional(CONF_DEVICE_CLASS, default=None):
                                    vol.Any(None, sensor.DEVICE_CLASSES_SCHEMA),
                                vol.Optional(CONF_STATE_CLASS, default=None): vol.Any(None, sensor.STATE_CLASSES_SCHEMA),
                                vol.Optional(CONF_UNIT_OF_MEASUREMENT, default=None): vol.Any(None, str),
                                vol.Required(CONF_COMPONENT): str,
                                vol.Required(CONF_CONTROL): str,
                                vol.Optional(CONF_SENSOR_ATTRIBUTE, default="String"): str,
                            })
                        ]),
                        CONF_SWITCH_PLATFORM: vol.Schema([
                            vol.Schema({
                                vol.Optional(CONF_ENTITY_NAME, default=None): vol.Any(None, str),
                                vol.Optional(CONF_DEVICE_CLASS, default=None):
                                    vol.Any(None, switch.DEVICE_CLASSES_SCHEMA),
                                vol.Required(CONF_COMPONENT): str,
                                vol.Required(CONF_CONTROL): str,
                            })
                        ]),
                        CONF_TEXT_PLATFORM: vol.Schema([
                            vol.Schema({
                                vol.Optional(CONF_ENTITY_NAME, default=None): vol.Any(None, str),
                                vol.Required(CONF_COMPONENT): str,
                                vol.Required(CONF_CONTROL): str,
                                vol.Optional(CONF_TEXT_MODE, default=None): vol.Any(None, text.TextMode),
                                vol.Optional(CONF_TEXT_MIN_LENGTH, default=None): vol.Any(None, int),
                                vol.Optional(CONF_TEXT_MAX_LENGTH, default=None): vol.Any(None, int),
                                vol.Optional(CONF_TEXT_PATTERN, default=None): vol.Any(None, str),
                            })
                        ]),
                    })
                })
            }
        )
    }),
}, extra=vol.ALLOW_EXTRA)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Your controller/hub specific code."""
    # Data that you want to share with your platforms
    hass.data[DOMAIN] = {
        CONF_CORES: {},
        CONF_CONFIG: config[DOMAIN],
    }

    async def handle_call_method(call: ServiceCall):
        """Handle the service call."""
        registry = dr.async_get(hass)

        for device_id in call.data["device_id"]:
            device: dr.DeviceEntry = registry.devices.get(device_id, None)
            if not device:
                continue

            core: qrc.Core = hass.data[DOMAIN][CONF_CORES].get(device.name)

            method = call.data.get(CALL_METHOD_NAME)
            params = call.data.get(CALL_METHOD_PARAMS)

            _LOGGER.info("call response: %s", await core.call(method, params))

    hass.services.async_register(DOMAIN, "call_method", handle_call_method)

    # TODO: set up values in hass.data to be used by async setup entry?
    # may use https://github.com/home-assistant/core/blob/dev/homeassistant/components/knx/__init__.py#L210
    # for inspiration

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Q-Sys QRC from a config entry."""
    c = qrc.Core(entry.data[CONF_HOST])
    core_runner_task = asyncio.create_task(c.run_until_stopped())
    entry.async_on_unload(lambda: core_runner_task.cancel() and None)
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][CONF_CORES][entry.data[CONF_CORE_NAME]] = c

    registry = dr.async_get(hass)
    # TODO: reconcile with docs https://developers.home-assistant.io/docs/device_registry_index
    # TODO: use name_by_user?
    device_entry = registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.data[CONF_CORE_NAME])},
        name=entry.data[CONF_CORE_NAME],
        manufacturer="Q-Sys",
        model="Core",
    )
    devices[entry.entry_id] = device_entry

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # polling = asyncio.create_task(h.run_poll())
    # entry.async_on_unload(lambda: polling.cancel() and None)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN][CONF_CORES].pop(entry.data[CONF_CORE_NAME])
        device_entry = devices.get(entry.entry_id)
        if device_entry:
            registry = dr.async_get(hass)
            registry.async_remove_device(device_entry.id)
        # if len(hass.data[DOMAIN][CONF_CORES]) == 0:
        #    del hass.data[DOMAIN]

    return unload_ok
