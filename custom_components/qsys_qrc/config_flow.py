"""Config flow for Q-Sys QRC integration."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries, data_entry_flow
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError

from .const import *
from .qsys import qrc

_LOGGER = logging.getLogger(__name__)

# TODO adjust the data schema to the data that you need
STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_CORE_NAME): str,
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_PORT, default=qrc.PORT): int,
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
    }
)


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate the user input allows us to connect.

    Data has the keys from STEP_USER_DATA_SCHEMA with values provided by the user.
    """
    # TODO validate the data can be used to set up a connection.

    # If your PyPI package is not built with async, pass your methods
    # to the executor:
    # await hass.async_add_executor_job(
    #     your_validate_func, data["username"], data["password"]
    # )

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
    except TimeoutError as e:
        raise CannotConnect from e
    finally:
        task.cancel()

    # If you cannot connect:
    # throw CannotConnect
    # If the authentication is wrong:
    # InvalidAuth

    return {CONF_USER_DATA: data, CONF_ENGINE_STATUS: status_response.get("result", {})}


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Q-Sys QRC."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        if user_input is None:
            suggested_name = "my_core"

            i = 1
            while (
                self.hass.data.get(DOMAIN, {})
                .get(CONF_CORES, {})
                .get(suggested_name, None)
            ):
                i += 1
                suggested_name = f"my_core_{i}"

            return self.async_show_form(
                step_id="user",
                data_schema=self.add_suggested_values_to_schema(
                    STEP_USER_DATA_SCHEMA,
                    {CONF_CORE_NAME: suggested_name},
                ),
            )

        if user_input[CONF_CORE_NAME] in self.hass.data[DOMAIN][CONF_CORES]:
            raise data_entry_flow.AbortFlow("already_configured")

        errors = {}
        try:
            data = await validate_input(self.hass, user_input)
        except CannotConnect:
            errors["base"] = "cannot_connect"
        except InvalidAuth:
            errors["base"] = "invalid_auth"
        except qrc.QRCError as e:  # pylint: disable=broad-except
            if e.error["code"] == 10:
                errors["base"] = "invalid_auth"
            else:
                _LOGGER.warn("Unexpected error: %s", repr(e))
                errors["base"] = "unknown"
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("Unexpected exception")
            errors["base"] = "unknown"
        else:
            return self.async_create_entry(
                title=f"{data[CONF_ENGINE_STATUS].get('DesignName', data[CONF_USER_DATA][CONF_CORE_NAME])}",
                data=data,
            )

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                STEP_USER_DATA_SCHEMA,
                user_input,
            ),
            errors=errors,
        )

    @staticmethod
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Create the options flow."""
        return OptionsFlowHandler(config_entry)


class OptionsFlowHandler(config_entries.OptionsFlow):
    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""
        if user_input is None:
            return self.async_show_form(
                step_id="init",
                data_schema=self.add_suggested_values_to_schema(
                    STEP_USER_DATA_SCHEMA,
                    self.config_entry.data[CONF_USER_DATA],
                ),
                description_placeholders={CONF_PASSWORD: "Usually 4 digits"},
            )

        # TODO: reduce duplication between config and options
        errors = {}
        try:
            data = await validate_input(self.hass, user_input)
            # TODO: handle timeouterror?
        except CannotConnect:
            errors["base"] = "cannot_connect"
        except InvalidAuth:
            errors["base"] = "invalid_auth"
        except qrc.QRCError as e:  # pylint: disable=broad-except
            if e.error["code"] == 10:
                errors["base"] = "invalid_auth"
            else:
                _LOGGER.warn("Unexpected error: %s", repr(e))
                errors["base"] = "unknown"
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("Unexpected exception")
            errors["base"] = "unknown"
        else:
            # await self.hass.config_entries.async_reload(self.config_entry.entry_id)
            if await self.hass.config_entries.async_unload(self.config_entry.entry_id):
                self.hass.config_entries.async_update_entry(
                    self.config_entry, data=data, options=self.config_entry.options
                )
                await self.hass.config_entries.async_reload(self.config_entry.entry_id)

            return self.async_create_entry(
                title="",
                data={},
            )

        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                STEP_USER_DATA_SCHEMA,
                user_input,
            ),
            errors=errors,
        )


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""
