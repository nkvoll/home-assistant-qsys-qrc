"""Assisted entity configuration using current QRC metadata."""

from copy import deepcopy
import json
import logging

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
    resolve_configuration,
)


_LOGGER = logging.getLogger(__name__)


def choose(values, multiple=False):
    """Build a native choice selector."""
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=values, multiple=multiple, mode=selector.SelectSelectorMode.DROPDOWN
        )
    )


class EntityFlowMixin:
    """Manage UI-owned mappings without modifying YAML definitions."""

    def __init__(self):
        super().__init__()
        self._component = None
        self._component_type = None
        self._control = None
        self._draft = None
        self._editing = None
        self._components = []
        self._controls = []
        self._warnings = []
        self._transfer = None
        self._review_original = None
        self._yaml_inventory = []

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
        current = (
            self.hass.data.get(DOMAIN, {})
            .get(CONF_ENTRY_INVENTORY, {})
            .get(self.config_entry.entry_id)
        )
        if current is not None:
            self._yaml_inventory = [
                deepcopy(item["mapping"])
                for item in current
                if item["source"] == "yaml"
            ]
        yaml = {CONF_PLATFORMS: {}}
        for mapping in self._yaml_inventory:
            yaml[CONF_PLATFORMS].setdefault(mapping["platform"], []).append(
                mapping["settings"]
            )
        # UI state comes from current options even while an options-triggered reload is running.
        return resolve_configuration(self.core_name, yaml, self.config_entry.options)[1]

    def _form(self, step, fields=None, error=None, field_errors=None, **placeholders):
        return self.async_show_form(
            step_id=step,
            data_schema=vol.Schema(fields or {}),
            errors={**({"base": error} if error else {}), **(field_errors or {})},
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
                    return await self.async_step_component_kind()
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

    async def async_step_component_kind(self, user_input=None):
        """Expose the registered menu step for supported media components."""
        return self.async_show_menu(
            step_id="component_kind", menu_options=["control", "media_player"]
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
        field_errors = {}
        if user_input is not None:
            try:
                submitted = {
                    key: None if value == "" and settings.get(key) is None else value
                    for key, value in user_input.items()
                }
                updated = {**settings, **submitted}
                self._draft = normalize_mapping({**self._draft, "settings": updated})
            except vol.Invalid as err:
                error = "invalid_settings"
                for item in getattr(err, "errors", [err]):
                    for field in reversed(getattr(item, "path", [])):
                        if isinstance(field, str) and field in settings:
                            field_errors[field] = "invalid_settings"
                            break
            except ValueError, TypeError:
                error = "invalid_settings"
            else:
                try:
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
                        index != self._editing
                        and identity(self.core_name, mapping) == key
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
                except discovery.DiscoveryError:
                    error = "discovery_failed"
                except vol.Invalid, ValueError, TypeError:
                    _LOGGER.exception(
                        "Unable to prepare the entity review from saved configuration"
                    )
                    error = "configuration_error"
        return self._form(
            "settings", self._settings_fields(), error, field_errors=field_errors
        )

    def _settings_fields(self):
        fields = {}
        for key, value in self._draft["settings"].items():
            if key in {"component", "control"}:
                continue
            validator = str
            if key in {"min", "max"} and self._draft["platform"] == "text":
                validator = vol.Coerce(int)
            elif isinstance(value, bool):
                validator = bool
            elif isinstance(value, (int, float)):
                validator = vol.Coerce(float)
            elif isinstance(value, list):
                validator = selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=value, multiple=True, custom_value=True
                    )
                )
            marker = vol.Optional(key, description={"suggested_value": value})
            fields[marker] = vol.Any(None, validator)
        return fields

    async def async_step_review(self, user_input=None):
        if user_input is None:
            self._review_original = deepcopy(dict(self.config_entry.options))
        if user_input is not None:
            if self._review_original != dict(self.config_entry.options):
                return self._form(
                    "review",
                    error="configuration_changed",
                    mapping="",
                    identity="",
                    warnings="Restart the edit to review current settings.",
                )
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
            self._save_options(options)
            return await self.async_step_init()
        return self._form(
            "review",
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
                if self._editing < 0:
                    raise ValueError("Invalid index")
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
                index = int(user_input["entity"])
                if index < 0:
                    raise ValueError("Invalid index")
                mappings.pop(index)
            except ValueError, IndexError:
                return self._form("remove_entity", error="invalid_selection")
            self._save_options(
                {
                    **self.config_entry.options,
                    "mapping_version": MAPPING_VERSION,
                    "mappings": mappings,
                }
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
                indices = [int(index) for index in user_input.get("entities", [])]
                if any(index < 0 or index >= len(yaml) for index in indices):
                    raise vol.Invalid("Invalid YAML selection")
                selected = (
                    yaml
                    if user_input.get("all")
                    else [yaml[index] for index in indices]
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
                    "skipped": [item for item in selected if item not in incoming],
                    "original": deepcopy(dict(self.config_entry.options)),
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
            self._save_options(
                {
                    **self.config_entry.options,
                    "mapping_version": MAPPING_VERSION,
                    "mappings": self._transfer["mappings"],
                }
            )
            return await self.async_step_yaml_cleanup()
        return self._form(
            "yaml_review",
            {vol.Required("confirm", default=False): bool},
            preview=json.dumps(
                {
                    key: self._transfer[key]
                    for key in ("selected", "skipped", "changes", "issues")
                },
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
                    "original": deepcopy(dict(self.config_entry.options)),
                    "new_ids": document["core_name"] != self.core_name,
                    "yaml": yaml,
                    "transfer_yaml": user_input.get("transfer_yaml", False),
                    "policies": {
                        str(index): user_input["collision"]
                        for index, change in enumerate(changes)
                        if change["action"] in {"skip", "replace"}
                        or change.get("ownership_transfer")
                    },
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
        if user_input:
            replacements = user_input.get("replace_collisions")
            policies = (
                self._transfer["policies"]
                if replacements is None
                else {
                    index: "replace" if index in replacements else "skip"
                    for index in self._transfer["policies"]
                }
            )
            if policies != self._transfer["policies"]:
                try:
                    proposed = deepcopy(self._transfer["original"].get("mappings", []))
                    changes = []
                    for index, mapping in enumerate(
                        self._transfer["document"]["mappings"]
                    ):
                        proposed, action = transfer_mappings(
                            self.core_name,
                            proposed,
                            [mapping],
                            self._transfer["yaml"],
                            collision=policies.get(str(index), "replace"),
                            transfer_yaml=self._transfer["transfer_yaml"],
                        )
                        changes.extend(action)
                    self._transfer["mappings"] = proposed
                    self._transfer["changes"] = changes
                    self._transfer["policies"] = policies
                except vol.Invalid:
                    return await self.async_step_import_portable()
                # A changed policy needs a fresh review before confirmation.
                return await self.async_step_portable_review()
        if user_input and user_input.get("confirm"):
            if dict(self.config_entry.options) != self._transfer["original"]:
                return self._form(
                    "portable_review",
                    error="configuration_changed",
                    preview="",
                    identity_notice="Restart import.",
                )
            self._save_options(
                {
                    **self.config_entry.options,
                    "mapping_version": MAPPING_VERSION,
                    "mappings": self._transfer["mappings"],
                }
            )
            return await self.async_step_init()
        return self._form(
            "portable_review",
            {
                vol.Required("confirm", default=False): bool,
                vol.Optional(
                    "replace_collisions",
                    description={
                        "suggested_value": [
                            index
                            for index, policy in self._transfer["policies"].items()
                            if policy == "replace"
                        ]
                    },
                ): choose(
                    [
                        {
                            "value": index,
                            "label": str(
                                self._transfer["changes"][int(index)]["identity"]
                            ),
                        }
                        for index in self._transfer["policies"]
                    ],
                    multiple=True,
                ),
            },
            preview=json.dumps(
                {
                    "counts": {
                        action: sum(
                            item["action"] == action
                            for item in self._transfer["changes"]
                        )
                        for action in ("add", "replace", "skip")
                    },
                    **{
                        key: self._transfer[key]
                        for key in ("document", "changes", "issues")
                    },
                },
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


class OptionsFlowHandler(EntityFlowMixin, config_entries.OptionsFlow):
    """Persist reviewed options through one integration reload listener."""

    def _save_options(self, options):
        self.hass.config_entries.async_update_entry(self.config_entry, options=options)
