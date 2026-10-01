"""The Q-Sys QRC integration."""

from __future__ import annotations

import asyncio
import logging

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import SERVICE_RELOAD, Platform
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.reload import async_integration_yaml_config
from homeassistant.helpers.service import async_register_admin_service
from homeassistant.helpers.typing import ConfigType

from .const import *
from .qsys import qrc
from .schema import CONFIG_SCHEMA
from .mapping import resolve_configuration, yaml_mappings
from .portable import export_document
from .changegroup import create_change_group_for_platform

PLATFORMS: list[Platform] = [
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.TEXT,
    Platform.MEDIA_PLAYER,
]

_LOGGER = logging.getLogger(__name__)

devices = {}


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Your controller/hub specific code."""
    # Data that you want to share with your platforms
    # Gracefully handle missing YAML config (component is config-flow driven)
    domain_conf = config.get(DOMAIN)
    if domain_conf is None:
        # Use empty validated config when not present
        domain_conf = CONFIG_SCHEMA({DOMAIN: {}})[DOMAIN]
        _LOGGER.warning(
            "No `qsys_qrc:` key found in configuration.yaml. See "
            "https://github.com/nkvoll/home-assistant-qsys-qrc/ "
            "for qsys_qrc entity configuration documentation"
        )

    else:
        # Validate provided YAML against schema
        try:
            domain_conf = CONFIG_SCHEMA({DOMAIN: domain_conf})[DOMAIN]
        except vol.Invalid as ex:
            _LOGGER.error("Invalid %s configuration: %s", DOMAIN, ex)
            return False

    hass.data[DOMAIN] = {CONF_CONFIG: domain_conf, CONF_CACHED_CORES: {}}

    async def export_configuration(call: ServiceCall):
        core_name = call.data["core_name"]
        entry = next(
            (
                item
                for item in hass.config_entries.async_entries(DOMAIN)
                if item.data.get(CONF_USER_DATA, {}).get(CONF_CORE_NAME) == core_name
            ),
            None,
        )
        if entry is None:
            raise ServiceValidationError("Unknown Core name")
        mappings = entry.options.get("mappings", [])
        if call.data.get("effective", False):
            config = hass.data[DOMAIN].get(CONF_ENTRY_CONFIG, {}).get(entry.entry_id)
            if config is None:
                raise ServiceValidationError(
                    "Load the Core entry before exporting effective configuration"
                )
            mappings = yaml_mappings(config, core_name)
        return {
            "configuration": export_document(
                core_name,
                mappings,
                entry.data.get(CONF_ENGINE_STATUS, {}).get("DesignName"),
            )
        }

    async_register_admin_service(
        hass,
        DOMAIN,
        "export_configuration",
        export_configuration,
        schema=vol.Schema(
            {
                vol.Required("core_name"): str,
                vol.Optional("effective", default=False): bool,
            }
        ),
        supports_response=SupportsResponse.ONLY,
    )

    async def handle_call_method(call: ServiceCall):
        """Handle the service call."""
        registry = dr.async_get(hass)

        _LOGGER.info("Call request: %s", call.data)

        config_entry_ids = set()

        device_ids = call.data.get(CALL_METHOD_DEVICE_ID, [])
        # support single string device_id as well as list of device_ids
        if isinstance(device_ids, str):
            device_ids = [device_ids]

        for device_id in device_ids:
            device: dr.DeviceEntry = registry.devices.get(device_id, None)

            for config_entry_id in device.config_entries:
                config_entry_ids.add(config_entry_id)

        if not config_entry_ids:
            raise ServiceValidationError("No matching Q-SYS device found for call")

        for config_entry_id in config_entry_ids:
            config_entry = hass.data[DOMAIN][CONF_CONFIG_ENTRIES].get(config_entry_id)

            if not config_entry:
                continue

        core: qrc.Core = hass.data[DOMAIN][CONF_CACHED_CORES].get(
            config_entry.data.get(CONF_USER_DATA, {}).get(CONF_CORE_NAME)
        )

        method = call.data.get(CALL_METHOD_NAME)
        params = call.data.get(CALL_METHOD_PARAMS)

        try:
            response = await core.call(method, params)
            _LOGGER.debug("Call response: %s", response)
            if call.return_response:
                return response
            return
        except qrc.QRCError as err:
            # Extract error message from QRCError and raise ServiceValidationError
            error_dict = err.error if hasattr(err, "error") else {}
            error_code = error_dict.get("code", "unknown")
            error_message = error_dict.get("message", str(err))
            raise ServiceValidationError(
                f"QRC Error (code {error_code}): {error_message}"
            ) from err

    hass.services.async_register(
        DOMAIN,
        "call_method",
        handle_call_method,
        supports_response=SupportsResponse.OPTIONAL,
    )

    # TODO: set up values in hass.data to be used by async setup entry?
    # may use https://github.com/home-assistant/core/blob/dev/homeassistant/components/knx/__init__.py#L210
    # for inspiration

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Q-Sys QRC from a config entry."""
    config = CONFIG_SCHEMA({DOMAIN: {}})[DOMAIN]

    _conf = await async_integration_yaml_config(hass, DOMAIN)
    if not _conf or DOMAIN not in _conf:
        _LOGGER.warning(
            "No `qsys_qrc:` key found in configuration.yaml. See "
            "https://github.com/nkvoll/home-assistant-qsys-qrc/ "
            "for qsys_qrc entity configuration documentation"
        )
    else:
        config = _conf[DOMAIN]

    # store config entry for lookup later
    hass.data[DOMAIN].setdefault(CONF_CONFIG_ENTRIES, {})[entry.entry_id] = entry

    user_data = entry.data[CONF_USER_DATA]
    c = qrc.Core(user_data[CONF_HOST], user_data.get(CONF_PORT, qrc.PORT))
    core_name = user_data[CONF_CORE_NAME]
    effective, inventory = resolve_configuration(
        core_name, config.get(CONF_CORES, {}).get(core_name, {}), entry.options
    )
    hass.data[DOMAIN].setdefault(CONF_ENTRY_CONFIG, {})[entry.entry_id] = effective
    hass.data[DOMAIN].setdefault(CONF_ENTRY_INVENTORY, {})[entry.entry_id] = inventory
    poller = create_change_group_for_platform(
        c, effective[CONF_CHANGEGROUP], "entities"
    )
    hass.data[DOMAIN].setdefault(CONF_ENTRY_POLLERS, {})[entry.entry_id] = poller

    async def options_updated(hass, updated_entry):
        await hass.config_entries.async_reload(updated_entry.entry_id)

    entry.async_on_unload(entry.add_update_listener(options_updated))

    # set up automatic logon
    async def logon():
        try:
            response = await asyncio.wait_for(
                c.logon(user_data[CONF_USERNAME], user_data[CONF_PASSWORD]), timeout=5
            )
        except qrc.QRCError as err:
            if err.error.get("code") == 10:
                entry.async_start_reauth(hass)
            raise
        else:
            if not response.get("result", False):
                entry.async_start_reauth(hass)

    c.set_on_connected_commands([logon])
    core_runner_task = asyncio.create_task(c.run_until_stopped())
    entry.async_on_unload(lambda: core_runner_task.cancel() and None)

    # use design name? might be harder for the user?
    hass.data[DOMAIN][CONF_CACHED_CORES][core_name] = c

    registry = dr.async_get(hass)
    # TODO: reconcile with docs https://developers.home-assistant.io/docs/device_registry_index
    # TODO: use name_by_user?
    device_entry = registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        # TODO: use design code? not sure how to link entities to device then...
        identifiers={
            (DOMAIN, core_name),
            (DOMAIN, entry.data[CONF_ENGINE_STATUS].get("DesignName")),
        },
        name=entry.data[CONF_ENGINE_STATUS].get("DesignName", "Unknown"),
        manufacturer="Q-Sys",
        model=entry.data[CONF_ENGINE_STATUS].get("Platform", "Unknown"),
    )
    devices[entry.entry_id] = device_entry

    for de in dr.async_entries_for_config_entry(registry, entry.entry_id):
        if de != device_entry:
            # each hub should only have one device entry..
            registry.async_remove_device(de.id)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    poller.start()

    async def _reload_integration(call: ServiceCall) -> None:
        """Reload the integration."""
        await hass.config_entries.async_reload(entry.entry_id)
        hass.bus.async_fire(f"event_{DOMAIN}_reloaded", context=call.context)

    async_register_admin_service(hass, DOMAIN, SERVICE_RELOAD, _reload_integration)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN][CONF_CACHED_CORES].pop(
            entry.data[CONF_USER_DATA][CONF_CORE_NAME], None
        )

        hass.data[DOMAIN].setdefault(CONF_CONFIG_ENTRIES, {}).pop(entry.entry_id, None)

        poller = hass.data[DOMAIN][CONF_ENTRY_POLLERS].pop(entry.entry_id)
        await poller.stop()
        hass.data[DOMAIN][CONF_ENTRY_CONFIG].pop(entry.entry_id, None)
        hass.data[DOMAIN][CONF_ENTRY_INVENTORY].pop(entry.entry_id, None)
        devices.pop(entry.entry_id, None)

    return unload_ok
