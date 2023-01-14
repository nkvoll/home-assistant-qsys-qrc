"""Platform for number integration."""
from __future__ import annotations

import asyncio
import math

from homeassistant.components import number
from homeassistant.components.number import (
    NumberEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import template, entity, device_registry
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import changegroup
from .common import (QSysComponentControlBase, id_for_component_control)
from .const import *
from .qsys import qrc


async def async_setup_entry(
        hass: HomeAssistant,
        entry: ConfigEntry,
        async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensor entities."""

    # TODO: remove restored entities that are no longer used?
    core: qrc.Core
    for core_name, core in hass.data[DOMAIN].get(CONF_CORES, {}).items():
        entities = {}

        poller = changegroup.ChangeGroupPoller(core, f"{__name__.rsplit('.', 1)[-1]}_platform")

        for number_config in hass.data[DOMAIN] \
                .get(CONF_CONFIG, {}) \
                .get(CONF_CORES, {}) \
                .get(core_name, []) \
                .get(CONF_PLATFORMS, {}) \
                .get(CONF_NUMBER_PLATFORM, []):
            component_name = number_config[CONF_COMPONENT]
            control_name = number_config[CONF_CONTROL]

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
                    number_config[CONF_CONTROL]
                ),
                number_config.get(CONF_ENTITY_NAME, None),
                component_name,
                control_name,
                number_config[CONF_NUMBER_MIN_VALUE],
                number_config[CONF_NUMBER_MAX_VALUE],
                number_config[CONF_NUMBER_STEP],
                number_config[CONF_NUMBER_MODE],
                change_template,
                value_template,
            )

            if control_number_entity.unique_id not in entities:
                entities[control_number_entity.unique_id] = control_number_entity
                async_add_entities([control_number_entity])

                await poller.subscribe_component_control_changes(
                    control_number_entity.on_core_change, component_name, control_name,
                )

        if len(entities) > 0:
            polling = asyncio.create_task(poller.run_while_core_running())
            entry.async_on_unload(lambda: polling.cancel() and None)


class QRCNumberEntity(QSysComponentControlBase, NumberEntity):
    def __init__(
            self, hass, core_name, core, unique_id, entity_name, component, control,
            min_value: float, max_value: float, step: float, mode: number.NumberMode,
            change_template: template.Template, value_template: template.Template,
    ) -> None:
        super().__init__(hass, core_name, core, unique_id, entity_name, component, control)
        self._attr_native_min_value = min_value
        self._attr_native_max_value = max_value
        self._attr_native_step = step
        self._attr_mode = mode
        self._change_template = change_template
        self._value_template = value_template

    # async def async_update(self):
    #    res = await self.core.component().get(self.component, [{"Name": self.control}])
    #    _LOGGER.info("maybe update: %s", res)

    async def on_control_changed(self, core, change):
        # TODO: figure out value vs native_value. Is that a better place for the conversion?
        value = change["Value"]
        if self._change_template:
            value = self._change_template.async_render(dict(change=change, value=value, math=math, round=round))
        self._attr_native_value = value

    async def async_set_native_value(self, value: float) -> None:
        """Update the current value."""
        if self._value_template:
            value = self._value_template.async_render(dict(value=value, math=math, round=round))
        await self.update_control({"Value": value})
