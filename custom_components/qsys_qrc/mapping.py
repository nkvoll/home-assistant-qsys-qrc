"""Versioned entity mappings and explicit configuration ownership."""

from copy import deepcopy
import json

import voluptuous as vol

from .const import *
from .schema import CONFIG_SCHEMA

MAPPING_VERSION = 1
PLATFORMS = ("switch", "number", "sensor", "text", "select", "media_player")


def identity(core_name, mapping):
    """Return the existing entity identity, including its platform."""
    settings = mapping["settings"]
    component = settings.get(CONF_COMPONENT) or None
    if mapping["platform"] == "media_player":
        return (core_name, "media_player", component)
    return (core_name, mapping["platform"], component, settings[CONF_CONTROL])


def normalize_mapping(mapping):
    """Validate one mapping using the same defaults as YAML."""
    if not isinstance(mapping, dict) or set(mapping) - {
        "platform",
        "settings",
        "imported_from_yaml",
        "yaml_snapshot",
    }:
        raise vol.Invalid("Invalid mapping fields")
    platform = mapping.get("platform")
    if platform not in PLATFORMS:
        raise vol.Invalid("Unsupported platform")
    normalized = CONFIG_SCHEMA(
        {
            DOMAIN: {
                CONF_CORES: {
                    "core": {CONF_PLATFORMS: {platform: [mapping.get("settings")]}}
                }
            }
        }
    )[DOMAIN][CONF_CORES]["core"][CONF_PLATFORMS][platform][0]
    if platform == "number":
        if normalized["min"] > normalized["max"] or normalized["step"] <= 0:
            raise vol.Invalid("Number range or step is invalid")
        if (
            not 0
            <= normalized["position_lower_limit"]
            < normalized["position_upper_limit"]
            <= 1
        ):
            raise vol.Invalid("Position limits must be increasing within 0..1")
    if platform == "text":
        minimum, maximum = normalized["min"], normalized["max"]
        if (minimum is not None and minimum < 0) or (
            maximum is not None and maximum < 0
        ):
            raise vol.Invalid("Text lengths must be nonnegative")
        if minimum is not None and maximum is not None and minimum > maximum:
            raise vol.Invalid("Text minimum exceeds maximum")
    if platform == "select" and len(set(normalized["options"])) != len(
        normalized["options"]
    ):
        raise vol.Invalid("Select choices must be unique")
    result = {"platform": platform, "settings": normalized}
    if "imported_from_yaml" in mapping:
        if not isinstance(mapping["imported_from_yaml"], bool):
            raise vol.Invalid("Invalid ownership marker")
        result["imported_from_yaml"] = mapping["imported_from_yaml"]
    if "yaml_snapshot" in mapping:
        result["yaml_snapshot"] = normalize_mapping(
            {"platform": platform, "settings": mapping["yaml_snapshot"]}
        )["settings"]
    # Round-trip enums into plain JSON values, retaining every setting.
    return json.loads(json.dumps(result, allow_nan=False))


def normalize_mappings(mappings, core_name):
    """Reject duplicate identities within one configuration source."""
    if not isinstance(mappings, list):
        raise vol.Invalid("Mappings must be a list")
    result = [normalize_mapping(mapping) for mapping in mappings]
    keys = [identity(core_name, mapping) for mapping in result]
    if len(set(keys)) != len(keys):
        raise vol.Invalid("Duplicate entity identity")
    return result


def yaml_mappings(core_config, core_name):
    """Normalize all six YAML platforms without losing settings."""
    return normalize_mappings(
        [
            {"platform": platform, "settings": settings}
            for platform, mappings in core_config.get(CONF_PLATFORMS, {}).items()
            for settings in mappings
        ],
        core_name,
    )


def resolve_configuration(core_name, core_config, options):
    """Resolve a fresh entry-local configuration and ownership inventory."""
    if options.get("mapping_version", MAPPING_VERSION) != MAPPING_VERSION:
        raise vol.Invalid("Unsupported mapping version")
    yaml = yaml_mappings(core_config, core_name)
    ui = normalize_mappings(options.get("mappings", []), core_name)
    yaml_by_id = {identity(core_name, mapping): mapping for mapping in yaml}
    ui_by_id = {identity(core_name, mapping): mapping for mapping in ui}
    effective = dict(yaml_by_id)
    inventory = []
    for key, mapping in ui_by_id.items():
        active = key not in yaml_by_id or mapping.get("imported_from_yaml", False)
        if active:
            effective[key] = mapping
        inventory.append(
            {
                "mapping": deepcopy(mapping),
                "source": "ui",
                "effective": active,
                "cleanup_pending": key in yaml_by_id
                and mapping.get("imported_from_yaml", False),
                "yaml_conflict": key in yaml_by_id
                and "yaml_snapshot" in mapping
                and mapping["yaml_snapshot"] != yaml_by_id[key]["settings"],
            }
        )
    for key, mapping in yaml_by_id.items():
        inventory.append(
            {
                "mapping": deepcopy(mapping),
                "source": "yaml",
                "effective": effective[key] is mapping,
            }
        )
    config = deepcopy(core_config)
    config[CONF_PLATFORMS] = {platform: [] for platform in PLATFORMS}
    for mapping in effective.values():
        config[CONF_PLATFORMS][mapping["platform"]].append(
            deepcopy(mapping["settings"])
        )
    config.setdefault(
        CONF_CHANGEGROUP, {CONF_POLL_INTERVAL: 1.0, CONF_REQUEST_TIMEOUT: 5.0}
    )
    return config, inventory


def transfer_mappings(
    core_name, current, incoming, yaml, collision="skip", transfer_yaml=False
):
    """Build an atomic import using explicit collision and ownership choices."""
    if collision not in {"skip", "replace"}:
        raise vol.Invalid("Invalid collision policy")
    result = normalize_mappings(current, core_name)
    incoming = normalize_mappings(incoming, core_name)
    yaml = normalize_mappings(yaml, core_name)
    yaml_by_id = {identity(core_name, item): item for item in yaml}
    positions = {identity(core_name, item): index for index, item in enumerate(result)}
    changes = []
    for mapping in incoming:
        key = identity(core_name, mapping)
        existing = positions.get(key)
        yaml_mapping = yaml_by_id.get(key)
        if (existing is not None or yaml_mapping is not None) and collision == "skip":
            changes.append({"identity": key, "action": "skip"})
            continue
        already_owned = existing is not None and result[existing].get(
            "imported_from_yaml", False
        )
        if yaml_mapping is not None and not transfer_yaml and not already_owned:
            raise vol.Invalid("Explicit YAML ownership transfer is required")
        mapping = deepcopy(mapping)
        if yaml_mapping is not None and (transfer_yaml or not already_owned):
            mapping["imported_from_yaml"] = True
            mapping["yaml_snapshot"] = deepcopy(yaml_mapping["settings"])
        elif existing is not None and result[existing].get("imported_from_yaml"):
            mapping["imported_from_yaml"] = True
            if "yaml_snapshot" in result[existing]:
                mapping["yaml_snapshot"] = deepcopy(result[existing]["yaml_snapshot"])
        if existing is None:
            positions[key] = len(result)
            result.append(mapping)
        else:
            result[existing] = mapping
        changes.append(
            {
                "identity": key,
                "action": "replace" if existing is not None else "add",
                "ownership_transfer": yaml_mapping is not None,
            }
        )
    return result, changes
