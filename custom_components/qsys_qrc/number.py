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
from .common import (QSysSensorBase, id_for_component_control)
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

        # can platform name be more dynamic than this?
        cg = core.change_group("number_domain")
        poller = changegroup.ChangeGroupPoller(core, cg)

        for number_config in hass.data[DOMAIN] \
                .get(CONF_CONFIG, {}) \
                .get(CONF_CORES, {}) \
                .get(core_name, []) \
                .get(CONF_PLATFORMS, {}) \
                .get(CONF_NUMBER_PLATFORM, []):
            component_name = number_config[CONF_COMPONENT]
            control_name = number_config[CONF_CONTROL]

            # need to fetch component and control config first?

            change_template = number_config[CONF_NUMBER_CHANGE_TEMPLATE]
            if change_template:
                change_template = template.Template(change_template, hass)

            value_template = number_config[CONF_NUMBER_VALUE_TEMPLATE]
            if value_template:
                value_template = template.Template(value_template, hass)

            control_number_entity = ControlNumber(
                core,
                number_config[CONF_ENTITY_ID] or id_for_component_control(
                    number_config[CONF_COMPONENT],
                    number_config[CONF_CONTROL]
                ),
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

                poller.subscribe_component_control_changes(
                    control_number_entity.on_changed, component_name, control_name,
                )

            await cg.add_component_control({
                "Name": component_name,
                "Controls": [
                    {"Name": control_name}
                ],
            })

        if len(entities) > 0:
            polling = asyncio.create_task(poller.run_poll())
            entry.async_on_unload(lambda: polling.cancel() and None)


class ControlNumber(QSysSensorBase, NumberEntity):
    def __init__(
            self, core, unique_id, component, control,
            min_value: float, max_value: float, step: float, mode: number.NumberMode,
            change_template: template.Template, value_template: template.Template,
    ) -> None:
        super().__init__(core, unique_id, component, control)
        self._attr_native_min_value = min_value
        self._attr_native_max_value = max_value
        self._attr_native_step = step
        self._attr_mode = mode
        self._change_template = change_template
        self._value_template = value_template

    # async def async_update(self):
    #    res = await self.core.component().get(self.component, [{"Name": self.control}])
    #    _LOGGER.info("maybe update: %s", res)

    async def on_control_changed(self, hub, change):
        value = change["Value"]
        if self._change_template:
            value = self._change_template.async_render(dict(change=change, value=value, math=math, round=round))
        self._attr_native_value = value

    async def async_set_native_value(self, value: float) -> None:
        """Update the current value."""
        if self._value_template:
            value = self._value_template.async_render(dict(value=value, math=math, round=round))
        await self.update_control({"Value": value})
