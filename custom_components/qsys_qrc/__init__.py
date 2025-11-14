"""The Q-Sys QRC integration."""
from __future__ import annotations

import asyncio
import logging

import voluptuous as vol
from homeassistant.components import media_player, number, sensor, switch, text
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import SERVICE_RELOAD, Platform
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.reload import async_integration_yaml_config
from homeassistant.helpers.service import async_register_admin_service
from homeassistant.helpers.typing import ConfigType

from .const import *
from .qsys import qrc

PLATFORMS: list[Platform] = [
    Platform.NUMBER,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.TEXT,
    Platform.MEDIA_PLAYER,
]

_LOGGER = logging.getLogger(__name__)

devices = {}

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                CONF_CORES: vol.Schema(
                    {
                        vol.basestring: vol.Schema(
                            {
                                # TODO: this seems largely wasteful because we're not globbing components, but explicitly configuring them
                                # leaving it in for now, but consider ripping it out for simplicity
                                vol.Optional(CONF_FILTER): vol.Schema(
                                    {
                                        vol.Optional(
                                            CONF_EXCLUDE_COMPONENT_CONTROL
                                        ): vol.Schema(
                                            {CONF_COMPONENT: str, CONF_CONTROL: str}
                                        )
                                    }
                                ),
                                vol.Optional(CONF_CHANGEGROUP, default={CONF_POLL_INTERVAL: 1.0, CONF_REQUEST_TIMEOUT: 5.0}): vol.Schema(
                                    {
                                        vol.Optional(
                                            CONF_POLL_INTERVAL, default=1.0
                                        ): vol.Coerce(float),
                                        vol.Optional(
                                            CONF_REQUEST_TIMEOUT, default=5.0
                                        ): vol.Coerce(float),
                                    }
                                ),
                                vol.Optional(CONF_PLATFORMS): vol.Schema(
                                    {
                                        CONF_MEDIA_PLAYER_PLATFORM: vol.Schema(
                                            [
                                                vol.Schema(
                                                    {
                                                        vol.Optional(
                                                            CONF_ENTITY_NAME,
                                                            default=None,
                                                        ): vol.Any(None, str),
                                                        vol.Optional(
                                                            CONF_DEVICE_CLASS,
                                                            default=None,
                                                        ): vol.Any(
                                                            None,
                                                            media_player.DEVICE_CLASSES_SCHEMA,
                                                        ),
                                                        vol.Required(
                                                            CONF_COMPONENT
                                                        ): str,
                                                    }
                                                )
                                            ]
                                        ),
                                        CONF_NUMBER_PLATFORM: vol.Schema(
                                            [
                                                vol.Schema(
                                                    {
                                                        vol.Optional(
                                                            CONF_ENTITY_NAME,
                                                            default=None,
                                                        ): vol.Any(None, str),
                                                        vol.Optional(
                                                            CONF_DEVICE_CLASS,
                                                            default=None,
                                                        ): vol.Any(
                                                            None,
                                                            number.DEVICE_CLASSES_SCHEMA,
                                                        ),
                                                        vol.Optional(
                                                            CONF_UNIT_OF_MEASUREMENT,
                                                            default=None,
                                                        ): vol.Any(None, str),
                                                        vol.Required(
                                                            CONF_COMPONENT
                                                        ): str,
                                                        vol.Required(CONF_CONTROL): str,
                                                        vol.Optional(
                                                            CONF_NUMBER_USE_POSITION,
                                                            default=False,
                                                        ): bool,
                                                        vol.Optional(
                                                            CONF_NUMBER_MIN_VALUE,
                                                            default=0.0,
                                                        ): vol.Coerce(float),
                                                        vol.Optional(
                                                            CONF_NUMBER_MAX_VALUE,
                                                            default=100.0,
                                                        ): vol.Coerce(float),
                                                        vol.Optional(
                                                            CONF_NUMBER_POSITION_LOWER_LIMIT,
                                                            default=0.0,
                                                        ): vol.Coerce(float),
                                                        vol.Optional(
                                                            CONF_NUMBER_POSITION_UPPER_LIMIT,
                                                            default=1.0,
                                                        ): vol.Coerce(float),
                                                        vol.Optional(
                                                            CONF_NUMBER_STEP,
                                                            default=1.0,
                                                        ): vol.Coerce(float),
                                                        vol.Optional(
                                                            CONF_NUMBER_MODE,
                                                            default=number.NumberMode.AUTO,
                                                        ): vol.Coerce(
                                                            number.NumberMode
                                                        ),
                                                        vol.Optional(
                                                            CONF_NUMBER_CHANGE_TEMPLATE,
                                                            default=None,
                                                        ): vol.Any(None, str),
                                                        vol.Optional(
                                                            CONF_NUMBER_VALUE_TEMPLATE,
                                                            default=None,
                                                        ): vol.Any(None, str),
                                                    }
                                                )
                                            ]
                                        ),
                                        CONF_SENSOR_PLATFORM: vol.Schema(
                                            [
                                                vol.Schema(
                                                    {
                                                        vol.Optional(
                                                            CONF_ENTITY_NAME,
                                                            default=None,
                                                        ): vol.Any(None, str),
                                                        vol.Optional(
                                                            CONF_DEVICE_CLASS,
                                                            default=None,
                                                        ): vol.Any(
                                                            None,
                                                            sensor.DEVICE_CLASSES_SCHEMA,
                                                        ),
                                                        vol.Optional(
                                                            CONF_STATE_CLASS,
                                                            default=None,
                                                        ): vol.Any(
                                                            None,
                                                            sensor.STATE_CLASSES_SCHEMA,
                                                        ),
                                                        vol.Optional(
                                                            CONF_UNIT_OF_MEASUREMENT,
                                                            default=None,
                                                        ): vol.Any(None, str),
                                                        vol.Required(
                                                            CONF_COMPONENT
                                                        ): str,
                                                        vol.Required(CONF_CONTROL): str,
                                                        vol.Optional(
                                                            CONF_SENSOR_ATTRIBUTE,
                                                            default="String",
                                                        ): str,
                                                    }
                                                )
                                            ]
                                        ),
                                        CONF_SWITCH_PLATFORM: vol.Schema(
                                            [
                                                vol.Schema(
                                                    {
                                                        vol.Optional(
                                                            CONF_ENTITY_NAME,
                                                            default=None,
                                                        ): vol.Any(None, str),
                                                        vol.Optional(
                                                            CONF_DEVICE_CLASS,
                                                            default=None,
                                                        ): vol.Any(
                                                            None,
                                                            switch.DEVICE_CLASSES_SCHEMA,
                                                        ),
                                                        vol.Required(
                                                            CONF_COMPONENT
                                                        ): str,
                                                        vol.Required(CONF_CONTROL): str,
                                                    }
                                                )
                                            ]
                                        ),
                                        CONF_TEXT_PLATFORM: vol.Schema(
                                            [
                                                vol.Schema(
                                                    {
                                                        vol.Optional(
                                                            CONF_ENTITY_NAME,
                                                            default=None,
                                                        ): vol.Any(None, str),
                                                        vol.Required(
                                                            CONF_COMPONENT
                                                        ): str,
                                                        vol.Required(CONF_CONTROL): str,
                                                        vol.Optional(
                                                            CONF_TEXT_MODE, default=None
                                                        ): vol.Any(None, text.TextMode),
                                                        vol.Optional(
                                                            CONF_TEXT_MIN_LENGTH,
                                                            default=None,
                                                        ): vol.Any(None, int),
                                                        vol.Optional(
                                                            CONF_TEXT_MAX_LENGTH,
                                                            default=None,
                                                        ): vol.Any(None, int),
                                                        vol.Optional(
                                                            CONF_TEXT_PATTERN,
                                                            default=None,
                                                        ): vol.Any(None, str),
                                                    }
                                                )
                                            ]
                                        ),
                                    }
                                ),
                            }
                        )
                    }
                )
            }
        ),
    },
    extra=vol.ALLOW_EXTRA,
)


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
            error_dict = err.error if hasattr(err, 'error') else {}
            error_code = error_dict.get('code', 'unknown')
            error_message = error_dict.get('message', str(err))
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
    # update stored config
    hass.data[DOMAIN][CONF_CONFIG] = config

    # store config entry for lookup later
    hass.data[DOMAIN].setdefault(CONF_CONFIG_ENTRIES, {})[entry.entry_id] = entry

    user_data = entry.data[CONF_USER_DATA]
    c = qrc.Core(user_data[CONF_HOST])
    core_name = user_data[CONF_CORE_NAME]

    # set up automatic logon
    async def logon():
        await c.logon(
            user_data[CONF_USERNAME],
            user_data[CONF_PASSWORD],
        )

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

        device_entry = devices.get(entry.entry_id)
        if device_entry:
            registry = dr.async_get(hass)
            registry.async_remove_device(device_entry.id)

    return unload_ok
