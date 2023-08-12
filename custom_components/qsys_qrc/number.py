"""Platform for number integration."""
from __future__ import annotations

import asyncio
import decimal
import logging
import math

from homeassistant.components import number
from homeassistant.components.number import NumberEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import template
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import changegroup
from .common import QSysComponentControlBase, id_for_component_control
from .const import *
from .qsys import qrc

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensor entities."""

    # TODO: remove restored entities that are no longer used?
    core_name = entry.data[CONF_USER_DATA][CONF_CORE_NAME]
    core: qrc.Core = hass.data[DOMAIN].get(CONF_CORES, {}).get(core_name)
    if core is None:
        return

    entities = {}

    poller = changegroup.ChangeGroupPoller(
        core, f"{__name__.rsplit('.', 1)[-1]}_platform"
    )

    core_config = (
        hass.data[DOMAIN].get(CONF_CONFIG, {}).get(CONF_CORES, {}).get(core_name, {})
    )

    exclude_component_controls = core_config.get(CONF_FILTER, {}).get(
        CONF_EXCLUDE_COMPONENT_CONTROL, []
    )

    for number_config in core_config.get(CONF_PLATFORMS, {}).get(
        CONF_NUMBER_PLATFORM, []
    ):
        component_name = number_config[CONF_COMPONENT]
        control_name = number_config[CONF_CONTROL]

        should_exclude = False
        for filter in exclude_component_controls:
            # TODO: support globbing?
            if (
                component_name == filter[CONF_COMPONENT]
                and control_name == filter[CONF_CONTROL]
            ):
                should_exclude = True
                break
        if should_exclude:
            continue

        # need to fetch component and control config first? at least if we want to default min/max etc

        change_template = number_config[CONF_NUMBER_CHANGE_TEMPLATE]
        if change_template:
            change_template = template.Template(change_template, hass)

        value_template = number_config[CONF_NUMBER_VALUE_TEMPLATE]
        if value_template:
            value_template = template.Template(value_template, hass)

        control_number_entity = QRCNumberEntity(
            hass,
            core_name,
            core,
            id_for_component_control(
                core_name,
                number_config[CONF_COMPONENT],
                number_config[CONF_CONTROL],
            ),
            number_config.get(CONF_ENTITY_NAME, None),
            component_name,
            control_name,
            number_config[CONF_NUMBER_USE_POSITION],
            number_config[CONF_NUMBER_POSITION_LOWER_LIMIT],
            number_config[CONF_NUMBER_POSITION_UPPER_LIMIT],
            number_config[CONF_NUMBER_MIN_VALUE],
            number_config[CONF_NUMBER_MAX_VALUE],
            number_config[CONF_NUMBER_STEP],
            number_config[CONF_NUMBER_MODE],
            change_template,
            value_template,
            number_config[CONF_DEVICE_CLASS],
            number_config[CONF_UNIT_OF_MEASUREMENT],
        )

        if control_number_entity.unique_id not in entities:
            entities[control_number_entity.unique_id] = control_number_entity
            async_add_entities([control_number_entity])

            poller.subscribe_run_loop_iteration_ending(
                control_number_entity.on_core_polling_ending
            )
            await poller.subscribe_component_control_changes(
                control_number_entity.on_core_change,
                component_name,
                control_name,
            )

    if len(entities) > 0:
        polling = asyncio.create_task(poller.run_while_core_running())

        def on_unload():
            polling.cancel()

        entry.async_on_unload(on_unload)


class QRCNumberEntity(QSysComponentControlBase, NumberEntity):
    def __init__(
        self,
        hass,
        core_name,
        core,
        unique_id,
        entity_name,
        component,
        control,
        use_position: bool,
        position_lower_limit: float,
        position_upper_limit: float,
        min_value: float,
        max_value: float,
        step: float,
        mode: number.NumberMode,
        change_template: template.Template,
        value_template: template.Template,
        device_class,
        unit_of_measurement,
    ) -> None:
        super().__init__(
            hass, core_name, core, unique_id, entity_name, component, control
        )

        self._attr_device_class = device_class
        self._attr_native_unit_of_measurement = unit_of_measurement

        self._use_position = use_position
        self._position_lower_limit = position_lower_limit
        self._position_upper_limit = position_upper_limit

        self._attr_native_min_value = min_value

        if self._use_position:
            self._attr_native_min_value = 0.0

        self._attr_native_max_value = max_value
        if self._use_position:
            self._attr_native_max_value = 100.0

        self._attr_native_step = step
        self._attr_mode = mode
        self._change_template = change_template
        self._value_template = value_template

        self._position_lower_limit_factor = (
            self._position_lower_limit
            * self._attr_native_max_value
            / self._position_upper_limit
        )

        self._round_decimals = -1 * decimal.Decimal(str(step)).as_tuple().exponent

    # async def async_update(self):
    #    res = await self.core.component().get(self.component, [{"Name": self.control}])
    #    _LOGGER.info("Maybe update: %s", res)

    async def on_control_changed(self, core, change):
        # TODO: figure out value vs native_value. Is that a better place for the conversion?
        value = change["Value"]

        if self._use_position:
            # value = change["Position"] * self._attr_native_max_value / self._position_upper_limit
            value = (
                change["Position"]
                * (self._attr_native_max_value + self._position_lower_limit_factor)
                - self._position_lower_limit_factor
            ) / self._position_upper_limit

        if self._change_template:
            # TODO: a better way to have defaults available?
            value = self._change_template.async_render(
                dict(change=change, value=value, math=math, round=round)
            )

        value = round(value, self._round_decimals)
        self._attr_native_value = max(
            self._attr_native_min_value, min(value, self._attr_native_max_value)
        )

    async def async_set_native_value(self, value: float) -> None:
        """Update the current value."""
        if self._use_position:
            position = (
                (value + self._position_lower_limit_factor)
                / (self._attr_native_max_value + self._position_lower_limit_factor)
            ) * self._position_upper_limit
            await self.update_control({"Position": position})
            return

        if self._value_template:
            # TODO: a better way to have defaults available?
            value = self._value_template.async_render(
                dict(value=value, math=math, round=round)
            )

        await self.update_control({"Value": value})
