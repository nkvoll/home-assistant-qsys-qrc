"""The Q-Sys QRC integration."""
from __future__ import annotations

import asyncio

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry

from .hub import Hub
from .qsys import core
from .const import DOMAIN

# TODO List the platforms that you want to support.
# For your initial PR, limit it to 1 platform.
# PLATFORMS: list[Platform] = [Platform.LIGHT]
PLATFORMS: list[Platform] = [Platform.SENSOR]


devices = dict()


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Q-Sys QRC from a config entry."""
    # TODO Store an API object for your platforms to access
    # hass.data[DOMAIN][entry.entry_id] = MyApi(...)

    c = core.Core(entry.data["host"])
    hub = Hub(c)
    core_runner_task = asyncio.create_task(c.run_until_stopped())
    entry.async_on_unload(core_runner_task.cancel)
    hass.data.setdefault(DOMAIN, dict())
    hass.data[DOMAIN][entry.entry_id] = hub

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    registry = dr.async_get(hass)
    device_entry = registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        connections={("host", entry.data["host"])},
        identifiers={(DOMAIN, entry.data["host"])},
        name="Q-Sys " + entry.data["host"],
        manufacturer="Q-Sys",
        model="Core",
    )
    devices[entry.entry_id] = device_entry

    entry.async_on_unload(asyncio.create_task(hub.run_poll()).cancel)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)
        device_entry = devices.get(entry.entry_id)
        if device_entry:
            registry = dr.async_get(hass)
            registry.async_remove_device(device_entry.id)
        if len(hass.data[DOMAIN]) == 0:
            del hass.data[DOMAIN]

    return unload_ok
