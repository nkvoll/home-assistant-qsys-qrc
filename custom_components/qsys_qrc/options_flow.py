"""Assisted entity configuration using current QRC metadata."""

from copy import deepcopy
import json

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers import selector

from .const import *
from . import discovery
from .mapping import MAPPING_VERSION, identity, normalize_mapping, normalize_mappings


def choose(values, multiple=False):
    """Build a native choice selector."""
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=values, multiple=multiple, mode=selector.SelectSelectorMode.DROPDOWN
        )
    )


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Manage UI-owned mappings without modifying YAML definitions."""

    def __init__(self):
        self._component = None
        self._component_type = None
        self._control = None
        self._draft = None
        self._editing = None
        self._components = []
        self._controls = []
        self._warnings = []

    @property
    def core_name(self):
        return self.config_entry.data[CONF_USER_DATA][CONF_CORE_NAME]

    @property
    def core(self):
        core = (
            self.hass.data.get(DOMAIN, {})
            .get(CONF_CACHED_CORES, {})
            .get(self.core_name)
        )
        if core is None:
            raise discovery.DiscoveryError("Core is unavailable")
        return core

    def _mappings(self):
        return deepcopy(self.config_entry.options.get("mappings", []))

    def _inventory(self):
        return (
            self.hass.data.get(DOMAIN, {})
            .get(CONF_ENTRY_INVENTORY, {})
            .get(self.config_entry.entry_id, [])
        )

    def _form(self, step, fields=None, error=None, **placeholders):
        return self.async_show_form(
            step_id=step,
            data_schema=vol.Schema(fields or {}),
            errors={"base": error} if error else {},
            description_placeholders=placeholders,
        )

    async def async_step_init(self, user_input=None):
        inventory = "\n".join(
            f"{item['source'].upper()} · {item['mapping']['platform']} · "
            f"{item['mapping']['settings'].get('component') or 'Named Control'} / "
            f"{item['mapping']['settings'].get('control', '')} · "
            f"{'active' if item['effective'] else 'overridden'}"
            + (" · YAML cleanup pending" if item.get("cleanup_pending") else "")
            + (" · YAML changed after transfer" if item.get("yaml_conflict") else "")
            for item in self._inventory()
        )
        return self.async_show_menu(
            step_id="init",
            menu_options=["add_entity", "edit_entity", "remove_entity", "finish"],
            description_placeholders={"inventory": inventory or "No entity mappings."},
        )

    async def async_step_finish(self, user_input=None):
        return self.async_create_entry(title="", data=dict(self.config_entry.options))

    async def async_step_add_entity(self, user_input=None):
        self._editing = None
        self._draft = None
        return self.async_show_menu(
            step_id="add_entity", menu_options=["component", "named_control"]
        )

    async def async_step_component(self, user_input=None):
        error = None
        try:
            self._components = await discovery.components(self.core)
            if user_input:
                item = next(
                    (
                        item
                        for item in self._components
                        if item["Name"] == user_input["component"]
                    ),
                    None,
                )
                if item is None:
                    raise discovery.DiscoveryError("Component is missing")
                self._component = item["Name"]
                self._component_type = item.get("Type")
                if self._component_type in discovery.MEDIA_COMPONENT_TYPES:
                    return self.async_show_menu(
                        step_id="component_kind",
                        menu_options=["control", "media_player"],
                    )
                return await self.async_step_control()
        except discovery.DiscoveryError:
            error = "discovery_failed"
        return self._form(
            "component",
            {
                vol.Required("component"): choose(
                    [
                        {
                            "value": item["Name"],
                            "label": f"{item['Name']} ({item.get('Type', 'unknown')})",
                        }
                        for item in self._components
                    ]
                )
            },
            error,
        )

    async def async_step_media_player(self, user_input=None):
        self._draft = normalize_mapping(
            {
                "platform": "media_player",
                "settings": {"component": self._component, "name": self._component},
            }
        )
        return await self.async_step_settings()

    async def async_step_control(self, user_input=None):
        error = None
        try:
            self._controls = await discovery.controls(self.core, self._component)
            if user_input:
                self._control = next(
                    (
                        item
                        for item in self._controls
                        if item["Name"] == user_input["control"]
                    ),
                    None,
                )
                if self._control is None:
                    raise discovery.DiscoveryError("Control is missing")
                return await self.async_step_entity_type()
        except discovery.DiscoveryError:
            error = "discovery_failed"
        return self._form(
            "control",
            {
                vol.Required("control"): choose(
                    [
                        {
                            "value": item["Name"],
                            "label": f"{item['Name']} · {item.get('Type', 'unknown')} · {item.get('Direction', 'direction unknown')}",
                        }
                        for item in self._controls
                    ]
                )
            },
            error,
        )

    async def async_step_named_control(self, user_input=None):
        error = None
        if user_input:
            try:
                self._control = await discovery.named_control(
                    self.core, user_input["control"]
                )
                self._component = None
                self._component_type = None
                return await self.async_step_entity_type()
            except discovery.DiscoveryError:
                error = "discovery_failed"
        return self._form("named_control", {vol.Required("control"): str}, error)

    async def async_step_entity_type(self, user_input=None):
        platforms = discovery.compatible_platforms(self._control)
        if user_input and user_input["platform"] in platforms:
            self._draft = normalize_mapping(
                {
                    "platform": user_input["platform"],
                    "settings": discovery.suggested_settings(
                        user_input["platform"], self._component, self._control
                    ),
                }
            )
            return await self.async_step_settings()
        return self._form(
            "entity_type",
            {vol.Required("platform"): choose(platforms)},
            writability="Writable choices are unverified because direction metadata is absent."
            if discovery.writable(self._control) is None
            else "",
        )

    async def async_step_settings(self, user_input=None):
        error = None
        settings = self._draft["settings"]
        if user_input is not None:
            try:
                updated = {**settings, **user_input}
                self._draft = normalize_mapping({**self._draft, "settings": updated})
                issues = await discovery.validate_mapping(self.core, self._draft)
                blocking = [
                    issue for issue in issues if issue != "writability_unverified"
                ]
                if blocking:
                    return self._form(
                        "settings", self._settings_fields(), "incompatible_control"
                    )
                self._warnings = issues
                key = identity(self.core_name, self._draft)
                mappings = self._mappings()
                if any(
                    index != self._editing and identity(self.core_name, mapping) == key
                    for index, mapping in enumerate(mappings)
                ) or any(
                    item["source"] == "yaml"
                    and identity(self.core_name, item["mapping"]) == key
                    and not self._draft.get("imported_from_yaml")
                    for item in self._inventory()
                ):
                    error = "duplicate_entity"
                else:
                    return await self.async_step_review()
            except vol.Invalid, ValueError, TypeError:
                error = "invalid_settings"
            except discovery.DiscoveryError:
                error = "discovery_failed"
        return self._form("settings", self._settings_fields(), error)

    def _settings_fields(self):
        fields = {}
        for key, value in self._draft["settings"].items():
            if key in {"component", "control"}:
                continue
            validator = str
            if isinstance(value, bool):
                validator = bool
            elif isinstance(value, (int, float)):
                validator = vol.Coerce(float)
            elif isinstance(value, list):
                validator = selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=value, multiple=True, custom_value=True
                    )
                )
            elif key in {"min", "max"} and self._draft["platform"] == "text":
                validator = vol.Coerce(int)
            marker = vol.Optional(key, description={"suggested_value": value})
            fields[marker] = vol.Any(None, validator)
        return fields

    async def async_step_review(self, user_input=None):
        if user_input and user_input.get("confirm"):
            mappings = self._mappings()
            if self._editing is None:
                mappings.append(self._draft)
            else:
                mappings[self._editing] = self._draft
            options = {
                **self.config_entry.options,
                "mapping_version": MAPPING_VERSION,
                "mappings": normalize_mappings(mappings, self.core_name),
            }
            self.hass.config_entries.async_update_entry(
                self.config_entry, options=options
            )
            return await self.async_step_init()
        return self._form(
            "review",
            {vol.Required("confirm", default=False): bool},
            mapping=json.dumps(self._draft, indent=2),
            identity=str(identity(self.core_name, self._draft)),
            warnings=", ".join(self._warnings),
        )

    def _ui_choices(self):
        return [
            {
                "value": str(index),
                "label": f"{mapping['platform']} · {mapping['settings'].get('name') or mapping['settings'].get('control') or mapping['settings']['component']}",
            }
            for index, mapping in enumerate(self._mappings())
        ]

    async def async_step_edit_entity(self, user_input=None):
        if user_input:
            try:
                self._editing = int(user_input["entity"])
                self._draft = normalize_mapping(self._mappings()[self._editing])
                return await self.async_step_settings()
            except ValueError, IndexError:
                return self._form("edit_entity", error="invalid_selection")
        return self._form(
            "edit_entity", {vol.Required("entity"): choose(self._ui_choices())}
        )

    async def async_step_remove_entity(self, user_input=None):
        if user_input and user_input.get("confirm"):
            mappings = self._mappings()
            try:
                mappings.pop(int(user_input["entity"]))
            except ValueError, IndexError:
                return self._form("remove_entity", error="invalid_selection")
            self.hass.config_entries.async_update_entry(
                self.config_entry,
                options={
                    **self.config_entry.options,
                    "mapping_version": MAPPING_VERSION,
                    "mappings": mappings,
                },
            )
            return await self.async_step_init()
        return self._form(
            "remove_entity",
            {
                vol.Required("entity"): choose(self._ui_choices()),
                vol.Required("confirm", default=False): bool,
            },
        )
