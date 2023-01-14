"""The Q-Sys QRC integration."""
from __future__ import annotations

import asyncio
import logging

import voluptuous as vol
from homeassistant.components import number
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.typing import ConfigType

from .const import *
from .qsys import core as qsyscore

# TODO List the platforms that you want to support.
# For your initial PR, limit it to 1 platform.
# PLATFORMS: list[Platform] = [Platform.LIGHT]
# PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.SWITCH, Platform.NUMBER, Platform.TEXT]
PLATFORMS: list[Platform] = [Platform.SWITCH, Platform.NUMBER, Platform.TEXT]

_LOGGER = logging.getLogger(__name__)

devices = dict()

CONFIG_SCHEMA = vol.Schema({
    DOMAIN: vol.Schema({
        CONF_CORES: vol.Schema(
            {
                vol.basestring: vol.Schema({
                    vol.Optional(CONF_PLATFORMS): vol.Schema({
                        CONF_SWITCH_PLATFORM: vol.Schema([
                            vol.Schema({
                                vol.Optional(CONF_ENTITY_ID, default=None): vol.Any(None, str),
                                vol.Required(CONF_COMPONENT): str,
                                vol.Required(CONF_CONTROL): str,
                            })
                        ]),
                        CONF_NUMBER_PLATFORM: vol.Schema([
                            vol.Schema({
                                vol.Optional(CONF_ENTITY_ID, default=None): vol.Any(None, str),
                                vol.Required(CONF_COMPONENT): str,
                                vol.Required(CONF_CONTROL): str,
                                vol.Optional(CONF_NUMBER_MIN_VALUE, default=0.0): vol.Coerce(float),
                                vol.Optional(CONF_NUMBER_MAX_VALUE, default=100.0): vol.Coerce(float),
                                vol.Optional(CONF_NUMBER_STEP, default=0.1): vol.Coerce(float),
                                vol.Optional(CONF_NUMBER_MODE, default=number.NumberMode.AUTO): vol.Coerce(
                                    number.NumberMode),
                                vol.Optional(CONF_NUMBER_CHANGE_TEMPLATE, default=None): vol.Any(None, str),
                                vol.Optional(CONF_NUMBER_VALUE_TEMPLATE, default=None): vol.Any(None, str),
                            })
                        ])
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

            core: qsyscore.Core = hass.data[DOMAIN][CONF_CORES].get(device.name)

            method = call.data.get(CALL_METHOD_NAME)
            params = call.data.get(CALL_METHOD_PARAMS)

            _LOGGER.info("call response: %s", await core._call(method, params))

    hass.services.async_register(DOMAIN, "call_method", handle_call_method)

    # TODO: set up values in hass.data to be used by async setup entry?
    # may use https://github.com/home-assistant/core/blob/dev/homeassistant/components/knx/__init__.py#L210
    # for inspiration

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Q-Sys QRC from a config entry."""
    c = qsyscore.Core(entry.data[CONF_HOST])
    core_runner_task = asyncio.create_task(c.run_until_stopped())
    entry.async_on_unload(lambda: core_runner_task.cancel() and None)
    hass.data.setdefault(DOMAIN, dict())
    hass.data[DOMAIN][CONF_CORES][entry.data[CONF_CORE_NAME]] = c

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

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
