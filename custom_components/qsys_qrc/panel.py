"""Admin panel API; reviewed, atomic mapping changes share options-flow rules."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import voluptuous as vol
from homeassistant.components import (
    binary_sensor,
    frontend,
    number,
    sensor,
    switch,
    text,
    websocket_api,
)
from homeassistant.components.http import StaticPathConfig
from homeassistant.components.panel_custom import async_register_panel
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.reload import async_integration_yaml_config

from .const import (
    DOMAIN,
    CONF_CACHED_CORES,
    CONF_CORE_NAME,
    CONF_USER_DATA,
    CONF_ENGINE_STATUS,
    CONF_CORES,
    CONF_ENTRY_INVENTORY,
)
from . import discovery
from .common import id_for_component, id_for_component_control
from .mapping import (
    identity,
    normalize_mappings,
    resolve_configuration,
    transfer_mappings,
    yaml_mappings,
    MAPPING_VERSION,
)
from .portable import parse_document, export_document, dump_document, MAX_MAPPINGS


def revision(entry, yaml):
    """Detect changes made in other tabs, options flows, or YAML."""
    return hashlib.sha256(
        json.dumps([dict(entry.options), yaml], sort_keys=True).encode()
    ).hexdigest()


async def context(hass, entry_id):
    entry = hass.config_entries.async_get_entry(entry_id)
    if entry is None or entry.domain != DOMAIN:
        raise vol.Invalid("Unknown Q-SYS Core")
    name = entry.data[CONF_USER_DATA][CONF_CORE_NAME]
    config = await async_integration_yaml_config(hass, DOMAIN) or {}
    raw = config.get(DOMAIN, {}).get(CONF_CORES, {}).get(name, {})
    yaml = yaml_mappings(raw, name)
    core = hass.data[DOMAIN][CONF_CACHED_CORES].get(name)
    return entry, name, raw, yaml, core


def build_changes(name, current, yaml, msg):
    """Produce a full validated replacement before committing any changes."""
    action = msg["operation"]
    if action in {"create", "import", "migrate"}:
        if action == "import":
            incoming = parse_document(msg.get("document", ""), name)["mappings"]
        elif action == "migrate":
            selected = {tuple(key) for key in msg.get("identities", [])}
            incoming = [item for item in yaml if identity(name, item) in selected]
            if not incoming:
                raise vol.Invalid("Select YAML mappings to migrate")
        else:
            incoming = msg.get("mappings", [])
        if not incoming or len(incoming) > MAX_MAPPINGS:
            raise vol.Invalid("Select between 1 and 1000 mappings")
        # Ownership markers can only be created by explicit migration/transfer.
        if any(set(item) != {"platform", "settings"} for item in incoming):
            raise vol.Invalid("Invalid mapping fields")
        if action == "migrate":
            result = deepcopy(current)
            changes = []
            existing = {identity(name, item) for item in current}
            for item in incoming:
                policy = (
                    msg.get("collision", "skip")
                    if identity(name, item) in existing
                    else "replace"
                )
                result, item_changes = transfer_mappings(
                    name, result, [item], yaml, policy, True
                )
                changes.extend(item_changes)
            return result, changes
        return transfer_mappings(
            name,
            current,
            incoming,
            yaml,
            msg.get("collision", "skip"),
            action == "migrate" or msg.get("transfer_yaml", False),
        )
    selected = {tuple(key) for key in msg.get("identities", [])}
    available = {identity(name, item) for item in current}
    if not selected or not selected <= available:
        raise vol.Invalid(
            "Select existing UI mappings; migrate YAML mappings before editing"
        )
    result, changes = [], []
    patch = msg.get("patch", {})
    if action == "edit" and (not patch or set(patch) & {"component", "control"}):
        raise vol.Invalid(
            "Supply settings to edit; component and control identities cannot be changed in bulk"
        )
    for item in deepcopy(current):
        key = identity(name, item)
        if key in selected:
            changes.append({"identity": key, "action": action})
            if action == "delete":
                if any(identity(name, other) == key for other in yaml):
                    changes[-1]["warning"] = (
                        "Deleting this UI mapping reactivates its definition configured via Home Assistant YAML"
                    )
                continue
            item["settings"].update(patch)
        result.append(item)
    return normalize_mappings(result, name), changes


async def dispatch(hass, msg):
    action = msg["operation"]
    if action == "overview":
        rows = []
        for entry in hass.config_entries.async_entries(DOMAIN):
            name = entry.data[CONF_USER_DATA][CONF_CORE_NAME]
            core = hass.data[DOMAIN][CONF_CACHED_CORES].get(name)
            rows.append(
                {
                    "entry_id": entry.entry_id,
                    "name": name,
                    "status": (await core.get_state()).name if core else "UNLOADED",
                    "last_error": core.last_error if core else None,
                    "engine": entry.data.get(CONF_ENGINE_STATUS, {}),
                    "entities": len(
                        hass.data[DOMAIN]
                        .get(CONF_ENTRY_INVENTORY, {})
                        .get(entry.entry_id, [])
                    ),
                }
            )
        return {"cores": rows}
    entry, name, raw, yaml, core = await context(hass, msg["entry_id"])
    if action == "inventory":
        _, inventory = resolve_configuration(name, raw, entry.options)
        registry = er.async_get(hass)
        for row in inventory:
            mapping = row["mapping"]
            settings = mapping["settings"]
            unique_id = (
                id_for_component(name, settings.get("component"))
                if mapping["platform"] == "media_player"
                else id_for_component_control(
                    name, settings.get("component"), settings["control"]
                )
            )
            entity_id = registry.async_get_entity_id(
                mapping["platform"], DOMAIN, unique_id
            )
            registered = registry.async_get(entity_id) if entity_id else None
            if registered and registered.config_entry_id == entry.entry_id:
                row["entity_id"] = entity_id
                row["entity_name"] = (
                    registered.name or settings.get("name") or registered.original_name
                )
        return {
            "inventory": inventory,
            "revision": revision(entry, yaml),
            "edit_choices": {
                "device_class": {
                    "number": [item.value for item in number.NumberDeviceClass],
                    "sensor": [item.value for item in sensor.SensorDeviceClass],
                    "binary_sensor": [
                        item.value for item in binary_sensor.BinarySensorDeviceClass
                    ],
                    "switch": [item.value for item in switch.SwitchDeviceClass],
                },
                "state_class": {
                    "sensor": [item.value for item in sensor.SensorStateClass]
                },
                "mode": {
                    "number": [item.value for item in number.NumberMode],
                    "text": [item.value for item in text.TextMode],
                },
            },
        }
    if action == "export":
        mappings = entry.options.get("mappings", [])
        if msg.get("effective"):
            effective, _ = resolve_configuration(name, raw, entry.options)
            mappings = yaml_mappings(effective, name)
        return {
            "document": dump_document(
                export_document(
                    name,
                    mappings,
                    entry.data.get(CONF_ENGINE_STATUS, {}).get("DesignName"),
                )
            )
        }
    if action in {"components", "controls", "named", "monitor", "values"}:
        if core is None:
            raise vol.Invalid("Core is not loaded")
        if action == "values":
            names = msg.get("names", [])
            if len(names) > 1000 or any(not isinstance(item, str) for item in names):
                raise vol.Invalid("Invalid control names")
            return {"controls": await discovery.values(core, msg["component"], names)}
        if action == "components":
            return {"components": await discovery.components(core)}
        if action in {"controls", "named"}:
            items = (
                await discovery.controls(core, msg["component"])
                if action == "controls"
                else [await discovery.named_control(core, msg["name"])]
            )
            component = msg.get("component") if action == "controls" else None
            return {
                "controls": [
                    {
                        "metadata": item,
                        "platforms": discovery.compatible_platforms(item),
                        "suggestions": {
                            p: discovery.suggested_settings(p, component, item)
                            for p in discovery.compatible_platforms(item)
                        },
                    }
                    for item in items
                ]
            }
        if "capture" in msg:
            core.protocol_capture = msg["capture"]
        if msg.get("clear"):
            core.protocol_frames.clear()
        return {"capture": core.protocol_capture, "frames": list(core.protocol_frames)}
    baseline = revision(entry, yaml)
    current = entry.options.get("mappings", [])
    result, changes = build_changes(name, current, yaml, msg)
    findings = []
    if action != "delete":
        changed = {
            tuple(item["identity"]) for item in changes if item["action"] != "skip"
        }
        for mapping in result:
            if identity(name, mapping) in changed:
                if core is None:
                    raise vol.Invalid("Load the Core to validate changes")
                findings.append(
                    {
                        "identity": identity(name, mapping),
                        "issues": await discovery.validate_mapping(core, mapping),
                    }
                )
    token = hashlib.sha256(
        json.dumps([baseline, result, changes, findings], sort_keys=True).encode()
    ).hexdigest()
    if msg.get("commit"):
        latest_entry, _, _, latest_yaml, _ = await context(hass, msg["entry_id"])
        if revision(latest_entry, latest_yaml) != baseline:
            raise vol.Invalid("Configuration changed; review the changes again")
        if any(
            set(finding["issues"])
            & {
                "read_only_mismatch",
                "incompatible_control",
                "unsupported_component_type",
            }
            for finding in findings
        ):
            raise vol.Invalid("Resolve incompatible mappings before saving")
        if msg.get("revision") != baseline or msg.get("review_token") != token:
            raise vol.Invalid(
                "Configuration or discovery changed; review the changes again"
            )
        # No await between revision comparison and update: commit is atomic on the HA loop.
        hass.config_entries.async_update_entry(
            entry,
            options={
                **entry.options,
                "mapping_version": MAPPING_VERSION,
                "mappings": result,
            },
        )
    return {
        "changes": changes,
        "findings": findings,
        "revision": baseline,
        "review_token": token,
        "saved": bool(msg.get("commit")),
    }


@websocket_api.websocket_command(
    {
        vol.Required("type"): "qsys_qrc/panel",
        vol.Required("operation"): vol.In(
            {
                "overview",
                "inventory",
                "components",
                "controls",
                "values",
                "named",
                "export",
                "import",
                "migrate",
                "create",
                "edit",
                "delete",
                "monitor",
            }
        ),
        vol.Optional("entry_id"): str,
        vol.Optional("component"): str,
        vol.Optional("names"): list,
        vol.Optional("name"): str,
        vol.Optional("document"): str,
        vol.Optional("mappings"): list,
        vol.Optional("identities"): list,
        vol.Optional("patch"): dict,
        vol.Optional("collision"): vol.In({"skip", "replace"}),
        vol.Optional("transfer_yaml"): bool,
        vol.Optional("effective"): bool,
        vol.Optional("capture"): bool,
        vol.Optional("clear"): bool,
        vol.Optional("commit"): bool,
        vol.Optional("revision"): str,
        vol.Optional("review_token"): str,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_panel(hass, connection, msg):
    """Handle authenticated admin requests without exposing connection credentials."""
    try:
        result = await dispatch(hass, msg)
    except (
        vol.Invalid,
        discovery.DiscoveryError,
        KeyError,
        TypeError,
        ValueError,
    ) as err:
        connection.send_error(msg["id"], "invalid_request", str(err))
    else:
        connection.send_result(msg["id"], result)


async def async_setup_panel(hass):
    """Serve bundled assets locally and register one panel for all Cores."""
    websocket_api.async_register_command(hass, websocket_panel)
    await hass.http.async_register_static_paths(
        [
            StaticPathConfig(
                "/qsys_qrc_static", str(Path(__file__).parent / "frontend"), False
            )
        ]
    )
    await async_register_panel(
        hass,
        frontend_url_path="qsys-qrc",
        webcomponent_name="qsys-qrc-panel",
        sidebar_icon="mdi:audio-input-xlr",
        module_url="/qsys_qrc_static/panel.js?v=2",
        require_admin=True,
        config_panel_domain=DOMAIN,
    )

    frontend.add_extra_js_url(hass, "/qsys_qrc_static/connectivity.js?v=1")
