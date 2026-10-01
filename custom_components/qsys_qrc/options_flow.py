"""Assisted entity configuration using current QRC metadata."""

from copy import deepcopy
import json

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers import selector

from .const import *
from . import discovery
from .portable import parse_document
from .mapping import (
    MAPPING_VERSION,
    identity,
    normalize_mapping,
    normalize_mappings,
    transfer_mappings,
)


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
        self._transfer = None

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
            menu_options=[
                "add_entity",
                "edit_entity",
                "remove_entity",
                "import_yaml",
                "import_portable",
                "export_portable",
                "finish",
            ],
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

    async def async_step_import_yaml(self, user_input=None):
        """Select YAML identities and preview complete settings before transfer."""
        yaml = [
            deepcopy(item["mapping"])
            for item in self._inventory()
            if item["source"] == "yaml"
        ]
        choices = [
            {
                "value": str(index),
                "label": f"{item['platform']} · {item['settings'].get('component') or 'Named Control'} / {item['settings'].get('control', '')}",
            }
            for index, item in enumerate(yaml)
        ]
        error = None
        if user_input:
            try:
                selected = (
                    yaml
                    if user_input.get("all")
                    else [
                        yaml[int(index)]
                        for index in user_input.get("entities", [])
                        if 0 <= int(index) < len(yaml)
                    ]
                )
                if not selected:
                    raise vol.Invalid("Select at least one mapping")
                # New transfers replace their YAML source; existing UI copies use the explicit retry policy.
                current = self._mappings()
                existing = {identity(self.core_name, item) for item in current}
                incoming = [
                    item
                    for item in selected
                    if identity(self.core_name, item) not in existing
                    or user_input.get("existing", "skip") == "replace"
                ]
                proposed, changes = transfer_mappings(
                    self.core_name,
                    current,
                    incoming,
                    yaml,
                    collision="replace",
                    transfer_yaml=True,
                )
                issues = []
                for item in incoming:
                    warnings = await discovery.validate_mapping(self.core, item)
                    issues.append(
                        {"identity": identity(self.core_name, item), "issues": warnings}
                    )
                self._transfer = {
                    "mappings": proposed,
                    "changes": changes,
                    "issues": issues,
                    "selected": incoming,
                    "original": deepcopy(self.config_entry.options),
                }
                return await self.async_step_yaml_review()
            except vol.Invalid, ValueError, IndexError:
                error = "invalid_selection"
            except discovery.DiscoveryError:
                error = "discovery_failed"
        return self._form(
            "import_yaml",
            {
                vol.Optional("entities"): choose(choices, multiple=True),
                vol.Optional("all", default=False): bool,
                vol.Required("existing", default="skip"): choose(["skip", "replace"]),
            },
            error,
        )

    async def async_step_yaml_review(self, user_input=None):
        """Commit the reviewed migration atomically and leave YAML cleanup to the user."""
        if user_input and user_input.get("confirm"):
            if dict(self.config_entry.options) != self._transfer["original"]:
                return self._form(
                    "yaml_review",
                    error="configuration_changed",
                    preview="",
                    cleanup="Restart the import to review current settings.",
                )
            self.hass.config_entries.async_update_entry(
                self.config_entry,
                options={
                    **self.config_entry.options,
                    "mapping_version": MAPPING_VERSION,
                    "mappings": self._transfer["mappings"],
                },
            )
            return await self.async_step_yaml_cleanup()
        return self._form(
            "yaml_review",
            {vol.Required("confirm", default=False): bool},
            preview=json.dumps(
                {key: self._transfer[key] for key in ("selected", "changes", "issues")},
                indent=2,
            ),
            cleanup="Transferred UI copies become authoritative immediately. Remove only the selected YAML definitions after saving. Core names and entity IDs stay unchanged.",
        )

    async def async_step_yaml_cleanup(self, user_input=None):
        if user_input is not None:
            return await self.async_step_init()
        return self._form(
            "yaml_cleanup", definitions=json.dumps(self._transfer["selected"], indent=2)
        )

    async def async_step_import_portable(self, user_input=None):
        """Parse pasted JSON and preview all settings, collisions, and discovery findings."""
        error = None
        if user_input:
            try:
                document = parse_document(user_input["document"], self.core_name)
                yaml = [
                    item["mapping"]
                    for item in self._inventory()
                    if item["source"] == "yaml"
                ]
                proposed, changes = transfer_mappings(
                    self.core_name,
                    self._mappings(),
                    document["mappings"],
                    yaml,
                    collision=user_input["collision"],
                    transfer_yaml=user_input.get("transfer_yaml", False),
                )
                issues = []
                for mapping in document["mappings"]:
                    findings = await discovery.validate_mapping(self.core, mapping)
                    issues.append(
                        {
                            "identity": identity(self.core_name, mapping),
                            "issues": findings,
                        }
                    )
                self._transfer = {
                    "mappings": proposed,
                    "changes": changes,
                    "issues": issues,
                    "document": document,
                    "original": deepcopy(self.config_entry.options),
                    "new_ids": document["core_name"] != self.core_name,
                }
                return await self.async_step_portable_review()
            except vol.Invalid, ValueError, TypeError, RecursionError:
                error = "invalid_document"
            except discovery.DiscoveryError:
                error = "discovery_failed"
        return self._form(
            "import_portable",
            {
                vol.Required("document"): selector.TextSelector(
                    selector.TextSelectorConfig(multiline=True)
                ),
                vol.Required("collision", default="skip"): choose(["skip", "replace"]),
                vol.Optional("transfer_yaml", default=False): bool,
            },
            error,
        )

    async def async_step_portable_review(self, user_input=None):
        if user_input and user_input.get("confirm"):
            if dict(self.config_entry.options) != self._transfer["original"]:
                return self._form(
                    "portable_review",
                    error="configuration_changed",
                    preview="",
                    identity_notice="Restart import.",
                )
            self.hass.config_entries.async_update_entry(
                self.config_entry,
                options={
                    **self.config_entry.options,
                    "mapping_version": MAPPING_VERSION,
                    "mappings": self._transfer["mappings"],
                },
            )
            return await self.async_step_init()
        return self._form(
            "portable_review",
            {vol.Required("confirm", default=False): bool},
            preview=json.dumps(
                {key: self._transfer[key] for key in ("document", "changes", "issues")},
                indent=2,
            ),
            identity_notice="The target Core has a different name. Imported mappings create new Home Assistant unique IDs."
            if self._transfer["new_ids"]
            else "The target Core name supplies the entity identity prefix.",
        )

    async def async_step_export_portable(self, user_input=None):
        if user_input is not None:
            return await self.async_step_init()
        return self._form("export_portable", core_name=self.core_name)
