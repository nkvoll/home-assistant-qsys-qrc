"""Configuration ownership and compatibility tests."""

import pytest

from custom_components.qsys_qrc.common import id_for_component_control, id_for_component
from custom_components.qsys_qrc.mapping import normalize_mappings, resolve_configuration
import voluptuous as vol


@pytest.mark.parametrize(
    "platform", ["switch", "number", "sensor", "text", "select", "media_player"]
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
