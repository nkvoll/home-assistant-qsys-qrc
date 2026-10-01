"""Configuration ownership and compatibility tests."""

import pytest

from custom_components.qsys_qrc.common import id_for_component_control, id_for_component
from custom_components.qsys_qrc.mapping import normalize_mappings, resolve_configuration
import voluptuous as vol


@pytest.mark.parametrize(
    "platform",
    ["switch", "number", "sensor", "binary_sensor", "text", "select", "media_player"],
)
def test_yaml_ui_defaults_and_identity(platform):
    settings = {"component": "component"}
    if platform != "media_player":
        settings["control"] = "control"
    yaml = {"platforms": {platform: [settings]}}
    original, _ = resolve_configuration("core", yaml, {})
    migrated, inventory = resolve_configuration(
        "core",
        yaml,
        {
            "mappings": [
                {"platform": platform, "settings": settings, "imported_from_yaml": True}
            ]
        },
    )
    removed, _ = resolve_configuration(
        "core",
        {},
        {
            "mappings": [
                {"platform": platform, "settings": settings, "imported_from_yaml": True}
            ]
        },
    )
    assert original == migrated == removed
    assert inventory[0]["cleanup_pending"]
    assert not inventory[1]["effective"]
    assert id_for_component("core", "component") == "core_component"
    assert id_for_component_control("core", None, "control") == "core__nc__control"
    assert (
        id_for_component_control("core", "component", "control")
        == "core_component_control"
    )


def test_ownership_and_independent_cores():
    yaml = {"platforms": {"switch": [{"control": "mute", "name": "YAML"}]}}
    ui = {
        "mappings": [
            {"platform": "switch", "settings": {"control": "mute", "name": "UI"}}
        ]
    }
    first, inventory = resolve_configuration("first", yaml, ui)
    second, _ = resolve_configuration("second", {}, ui)
    assert first["platforms"]["switch"][0]["name"] == "YAML"
    assert not inventory[0]["effective"]
    assert second["platforms"]["switch"][0]["name"] == "UI"
    second["platforms"]["switch"][0]["name"] = "changed"
    assert ui["mappings"][0]["settings"]["name"] == "UI"


def test_duplicate_identity_and_cross_platform():
    mapping = {"platform": "switch", "settings": {"control": "mute"}}
    with pytest.raises(vol.Invalid, match="Duplicate"):
        normalize_mappings([mapping, mapping], "core")
    assert (
        len(normalize_mappings([mapping, {**mapping, "platform": "sensor"}], "core"))
        == 2
    )


def test_yaml_conflict_and_settings_preserved():
    settings = {
        "control": "gain",
        "min": -80,
        "max": 10,
        "step": 0.5,
        "change_template": "{{ value * 2 }}",
        "value_template": "{{ value / 2 }}",
    }
    mapping = {
        "platform": "number",
        "settings": settings,
        "imported_from_yaml": True,
        "yaml_snapshot": settings,
    }
    config, inventory = resolve_configuration(
        "core",
        {"platforms": {"number": [{**settings, "max": 20}]}},
        {"mappings": [mapping]},
    )
    assert inventory[0]["yaml_conflict"]
    for key, value in settings.items():
        assert config["platforms"]["number"][0][key] == value


def test_platform_configuration_is_entry_local():
    from types import SimpleNamespace
    from custom_components.qsys_qrc.common import config_for_core, poller_for_entry
    from custom_components.qsys_qrc.const import (
        DOMAIN,
        CONF_ENTRY_CONFIG,
        CONF_ENTRY_POLLERS,
    )

    first = SimpleNamespace(entry_id="first")
    second = SimpleNamespace(entry_id="second")
    shared = object()
    hass = SimpleNamespace(
        data={
            DOMAIN: {
                CONF_ENTRY_CONFIG: {
                    "first": {"platforms": {"switch": []}},
                    "second": {"platforms": {"number": []}},
                },
                CONF_ENTRY_POLLERS: {"first": shared, "second": object()},
            }
        }
    )
    assert config_for_core(hass, first) != config_for_core(hass, second)
    assert poller_for_entry(hass, first) is shared
    assert poller_for_entry(hass, second) is not shared


def test_atomic_transfer_requires_explicit_ownership_and_is_idempotent():
    from custom_components.qsys_qrc.mapping import transfer_mappings

    mapping = {
        "platform": "select",
        "settings": {"control": "source", "options": ["A", "B"]},
    }
    with pytest.raises(vol.Invalid, match="ownership"):
        transfer_mappings("core", [], [mapping], [mapping], collision="replace")
    migrated, changes = transfer_mappings(
        "core", [], [mapping], [mapping], collision="replace", transfer_yaml=True
    )
    assert changes[0]["ownership_transfer"]
    assert migrated[0]["yaml_snapshot"]["options"] == ["A", "B"]
    retried, changes = transfer_mappings(
        "core", migrated, [mapping], [mapping], collision="skip"
    )
    assert retried == migrated
    assert changes[0]["action"] == "skip"
    changed = {**mapping, "settings": {**mapping["settings"], "options": ["C"]}}
    replaced, _ = transfer_mappings(
        "core", migrated, [changed], [mapping], collision="replace", transfer_yaml=True
    )
    assert len(replaced) == 1
    assert replaced[0]["settings"]["options"] == ["C"]
    assert mapping["settings"]["options"] == ["A", "B"]


@pytest.mark.parametrize(
    "mapping",
    [
        {"platform": "number", "settings": {"control": "gain", "step": 0}},
        {"platform": "number", "settings": {"control": "gain", "min": 20, "max": 10}},
        {
            "platform": "number",
            "settings": {"control": "gain", "position_upper_limit": 2},
        },
        {"platform": "text", "settings": {"control": "label", "min": 10, "max": 2}},
        {
            "platform": "select",
            "settings": {"control": "choice", "options": ["A", "A"]},
        },
    ],
)
def test_reject_invalid_behavior_settings(mapping):
    with pytest.raises(vol.Invalid):
        normalize_mappings([mapping], "core")


def test_identity_keys_match_platform_scope():
    from custom_components.qsys_qrc.mapping import identity

    assert identity(
        "core", {"platform": "media_player", "settings": {"component": "player"}}
    ) == ("core", "media_player", "player")
    assert identity(
        "core", {"platform": "switch", "settings": {"control": "mute"}}
    ) == ("core", "switch", None, "mute")


def test_portable_replace_preserves_existing_yaml_ownership_snapshot():
    from custom_components.qsys_qrc.mapping import transfer_mappings

    original = {
        "platform": "switch",
        "settings": {"control": "mute", "name": "Original"},
    }
    imported, _ = transfer_mappings("core", [], [original], [original], "replace", True)
    changed_yaml = {
        **original,
        "settings": {**original["settings"], "name": "Changed YAML"},
    }
    incoming = {
        **original,
        "settings": {**original["settings"], "name": "Portable update"},
    }
    result, _ = transfer_mappings(
        "core", imported, [incoming], [changed_yaml], "replace"
    )
    assert result[0]["imported_from_yaml"]
    assert result[0]["yaml_snapshot"]["name"] == "Original"
    _, inventory = resolve_configuration(
        "core",
        {"platforms": {"switch": [changed_yaml["settings"]]}},
        {"mappings": result},
    )
    assert inventory[0]["yaml_conflict"]
