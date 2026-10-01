"""Config flow for Q-Sys QRC integration."""

from __future__ import annotations

import asyncio
from contextlib import suppress
import logging
import math
from typing import Any
from types import SimpleNamespace

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .const import *
from .qsys import qrc
from .options_flow import OptionsFlowHandler, EntityFlowMixin
from .discovery import FlowCore
from .mapping import core_polling_settings, resolve_configuration
from homeassistant.helpers.reload import async_integration_yaml_config

_LOGGER = logging.getLogger(__name__)

def positive_seconds(value):
    """Reject nonpositive or nonfinite polling durations."""
    value = vol.Coerce(float)(value)
    if not math.isfinite(value) or value <= 0:
        raise vol.Invalid("Enter a positive, finite number of seconds")
    return value


STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_CORE_NAME): vol.All(str, vol.Length(min=1)),
        vol.Required(CONF_HOST): vol.All(str, vol.Length(min=1)),
        vol.Required(CONF_PORT, default=qrc.PORT): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=65535)
        ),
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Required(CONF_POLL_INTERVAL, default=1.0): positive_seconds,
        vol.Required(CONF_REQUEST_TIMEOUT, default=5.0): positive_seconds,
    }
)


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate the user input allows us to connect.

    Data has the keys from STEP_USER_DATA_SCHEMA with values provided by the user.
    """
    c = qrc.Core(data[CONF_HOST], data[CONF_PORT])
    task = asyncio.create_task(c.run_until_stopped())
    status_response = {}
    try:
        await asyncio.wait_for(c.wait_until_running(), timeout=5)
        res = await asyncio.wait_for(
            c.logon(data[CONF_USERNAME], data[CONF_PASSWORD]), timeout=5
        )
        if not res.get("result", False):
            raise InvalidAuth

        status_response = await asyncio.wait_for(c.status_get(), timeout=5)
        if not isinstance(status_response, dict) or not isinstance(
            status_response.get("result"), dict
        ):
            raise CannotConnect
    except (TimeoutError, OSError) as e:
        raise CannotConnect from e
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    return {CONF_USER_DATA: data, CONF_ENGINE_STATUS: status_response.get("result", {})}


class ConfigFlow(EntityFlowMixin, config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Q-Sys QRC."""

    VERSION = 1

    def __init__(self):
        super().__init__()
        self._initial_entry = SimpleNamespace(entry_id=None, data={}, options={})
        self._initial_inventory = []

    @property
    def config_entry(self):
        return self._initial_entry

    @property
    def core(self):
        return FlowCore(self._initial_entry.data[CONF_USER_DATA])

    def _inventory(self):
        return self._initial_inventory

    def _save_options(self, options):
        self._initial_entry.options = options

    async def async_step_init(self, user_input=None):
        return await self.async_step_setup_entities()

    async def async_step_setup_entities(self, user_input=None):
        """Expose the registered initial entity menu step."""
        return self.async_show_menu(
            step_id="setup_entities", menu_options=["add_entity", "finish"]
        )

    async def async_step_finish(self, user_input=None):
        data = self._initial_entry.data
        return self.async_create_entry(
            title=data[CONF_ENGINE_STATUS].get(
                "DesignName", data[CONF_USER_DATA][CONF_CORE_NAME]
            ),
            data=data,
            options=self._initial_entry.options,
        )

    def _duplicate(self, data, entry_id=None):
        """Include unloaded and legacy entries when checking identities."""
        for entry in self._async_current_entries():
            if entry.entry_id == entry_id:
                continue
            existing = entry.data.get(CONF_USER_DATA, {})
            if existing.get(CONF_CORE_NAME) == data[CONF_CORE_NAME] or (
                str(existing.get(CONF_HOST, "")).strip().lower()
                == data[CONF_HOST].strip().lower()
                and existing.get(CONF_PORT, qrc.PORT) == data[CONF_PORT]
            ):
                return True
        return False

    async def _connection_step(self, step_id, user_input=None, entry=None):
        errors = {}
        suggested = (
            dict(entry.data[CONF_USER_DATA]) if entry else {CONF_CORE_NAME: "my_core"}
        )
        yaml = await async_integration_yaml_config(self.hass, DOMAIN)
        core_name = suggested[CONF_CORE_NAME]
        if not entry and user_input:
            core_name = user_input.get(CONF_CORE_NAME, core_name)
        core_config = (
            (yaml or {}).get(DOMAIN, {}).get(CONF_CORES, {}).get(core_name, {})
        )
        suggested.update(core_polling_settings(core_config, suggested))
        if user_input is not None:
            suggested.update(user_input)
            if entry:
                suggested[CONF_CORE_NAME] = entry.data[CONF_USER_DATA][CONF_CORE_NAME]
            try:
                submitted = STEP_USER_DATA_SCHEMA(suggested)
                if self._duplicate(submitted, entry.entry_id if entry else None):
                    return self.async_abort(reason="already_configured")
                data = await validate_input(self.hass, submitted)
            except vol.Invalid:
                errors["base"] = "invalid_connection"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except qrc.QRCError as err:
                errors["base"] = (
                    "invalid_auth" if err.error.get("code") == 10 else "cannot_connect"
                )
            except Exception:
                _LOGGER.exception("Unexpected connection validation error")
                errors["base"] = "unknown"
            else:
                if entry:
                    return self.async_update_reload_and_abort(
                        entry,
                        data=data,
                        unique_id=entry.unique_id
                        or entry.data[CONF_USER_DATA][CONF_CORE_NAME],
                        reason="reauth_successful"
                        if step_id == "reauth_confirm"
                        else "reconfigure_successful",
                    )
                await self.async_set_unique_id(submitted[CONF_CORE_NAME])
                self._abort_if_unique_id_configured()
                self._initial_entry.data = data
                _, self._initial_inventory = resolve_configuration(
                    submitted[CONF_CORE_NAME], core_config, {}
                )
                return await self.async_step_init()

        schema = STEP_USER_DATA_SCHEMA
        if entry:
            # Core name is part of every entity ID. Reconnection preserves it.
            schema = vol.Schema(
                {
                    key: value
                    for key, value in schema.schema.items()
                    if str(key) != CONF_CORE_NAME
                }
            )
        return self.async_show_form(
            step_id=step_id,
            data_schema=self.add_suggested_values_to_schema(schema, suggested),
            errors=errors,
        )

    async def async_step_user(self, user_input=None):
        """Configure a new Core connection."""
        return await self._connection_step("user", user_input)

    async def async_step_reconfigure(self, user_input=None):
        """Reconnect without changing the identity prefix."""
        return await self._connection_step(
            "reconfigure", user_input, self._get_reconfigure_entry()
        )

    async def async_step_reauth(self, entry_data):
        """Start credential recovery for an existing Core."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input=None):
        """Validate replacement credentials and reload once."""
        return await self._connection_step(
            "reauth_confirm", user_input, self._get_reauth_entry()
        )

    @staticmethod
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Create the options flow."""
        return OptionsFlowHandler()


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""
