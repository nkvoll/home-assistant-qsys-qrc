"""Shared YAML and entity mapping validation."""

import voluptuous as vol
from homeassistant.components import (
    binary_sensor,
    media_player,
    number,
    sensor,
    switch,
    text,
)

from .const import *

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                CONF_CORES: vol.Schema(
                    {
                        str: vol.Schema(
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
                                vol.Optional(
                                    CONF_CHANGEGROUP,
                                    default={
                                        CONF_POLL_INTERVAL: 1.0,
                                        CONF_REQUEST_TIMEOUT: 5.0,
                                    },
                                ): vol.Schema(
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
                                                        vol.Optional(
                                                            CONF_COMPONENT,
                                                            default=None,
                                                        ): vol.Any(None, str),
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
                                                        vol.Optional(
                                                            CONF_COMPONENT,
                                                            default=None,
                                                        ): vol.Any(None, str),
                                                        vol.Required(CONF_CONTROL): str,
                                                        vol.Optional(
                                                            CONF_SENSOR_ATTRIBUTE,
                                                            default="String",
                                                        ): str,
                                                    }
                                                )
                                            ]
                                        ),
                                        CONF_BINARY_SENSOR_PLATFORM: vol.Schema(
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
                                                            binary_sensor.DEVICE_CLASSES_SCHEMA,
                                                        ),
                                                        vol.Optional(
                                                            CONF_COMPONENT,
                                                            default=None,
                                                        ): vol.Any(None, str),
                                                        vol.Required(CONF_CONTROL): str,
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
                                                        vol.Optional(
                                                            CONF_COMPONENT,
                                                            default=None,
                                                        ): vol.Any(None, str),
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
                                                        vol.Optional(
                                                            CONF_COMPONENT,
                                                            default=None,
                                                        ): vol.Any(None, str),
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
                                        CONF_SELECT_PLATFORM: vol.Schema(
                                            [
                                                vol.Schema(
                                                    {
                                                        vol.Optional(
                                                            CONF_ENTITY_NAME,
                                                            default=None,
                                                        ): vol.Any(None, str),
                                                        vol.Optional(
                                                            CONF_COMPONENT,
                                                            default=None,
                                                        ): vol.Any(None, str),
                                                        vol.Required(CONF_CONTROL): str,
                                                        vol.Optional(
                                                            CONF_SELECT_OPTIONS,
                                                            default=[],
                                                        ): vol.All(list, [str]),
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
