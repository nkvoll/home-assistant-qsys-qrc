"""Assisted options flow behavior with mocked QRC discovery."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from custom_components.qsys_qrc.options_flow import OptionsFlowHandler
from custom_components.qsys_qrc.const import *


def flow_for(mappings=None, inventory=None):
    entry = SimpleNamespace(
        entry_id="entry",
        data={CONF_USER_DATA: {CONF_CORE_NAME: "core"}},
        options={"mappings": mappings or []},
    )
    flow = OptionsFlowHandler()
    flow.handler = "entry"

    def update(entry, options):
        entry.options = options

    flow.hass = SimpleNamespace(
        data={
            DOMAIN: {
                CONF_CACHED_CORES: {"core": Mock()},
                CONF_ENTRY_INVENTORY: {"entry": inventory or []},
            }
        },
        config_entries=SimpleNamespace(
            async_get_known_entry=lambda _: entry,
            async_update_entry=Mock(side_effect=update),
        ),
    )
    return flow, entry


@pytest.mark.asyncio
async def test_assisted_add_review_and_remove():
    flow, entry = flow_for()
    with (
        patch(
            "custom_components.qsys_qrc.options_flow.discovery.components",
            AsyncMock(return_value=[{"Name": "gain", "Type": "gain"}]),
        ),
        patch(
            "custom_components.qsys_qrc.options_flow.discovery.controls",
            AsyncMock(
                return_value=[
                    {"Name": "mute", "Type": "Boolean", "Direction": "Read/Write"}
                ]
            ),
        ),
        patch(
            "custom_components.qsys_qrc.options_flow.discovery.validate_mapping",
            AsyncMock(return_value=[]),
        ),
    ):
        result = await flow.async_step_component({"component": "gain"})
        assert result["step_id"] == "component_kind"
        result = await flow.async_step_control({"control": "mute"})
        assert result["step_id"] == "entity_type"
        result = await flow.async_step_entity_type({"platform": "switch"})
        assert result["step_id"] == "settings"
        result = await flow.async_step_settings({"name": "Mute"})
        assert result["step_id"] == "review"
        assert not entry.options["mappings"]
        result = await flow.async_step_review({})
        assert result["step_id"] == "init"
        assert entry.options["mappings"][0]["settings"]["name"] == "Mute"
        assert flow.hass.config_entries.async_update_entry.call_count == 1
        await flow.async_step_remove_entity({"entity": "0", "confirm": True})
        assert not entry.options["mappings"]


@pytest.mark.asyncio
async def test_named_control_discovery_error_keeps_saved_mapping():
    from custom_components.qsys_qrc.discovery import DiscoveryError

    flow, entry = flow_for([{"platform": "switch", "settings": {"control": "old"}}])
    with patch(
        "custom_components.qsys_qrc.options_flow.discovery.named_control",
        AsyncMock(side_effect=DiscoveryError()),
    ):
        result = await flow.async_step_named_control({"control": "missing"})
    assert result["errors"]["base"] == "discovery_failed"
    assert len(entry.options["mappings"]) == 1
    flow.hass.config_entries.async_update_entry.assert_not_called()


@pytest.mark.asyncio
async def test_yaml_duplicate_and_edit_keeps_ownership():
    mapping = {
        "platform": "number",
        "settings": {"control": "level"},
        "imported_from_yaml": True,
    }
    flow, entry = flow_for(
        [mapping], [{"source": "yaml", "effective": False, "mapping": mapping}]
    )
    with patch(
        "custom_components.qsys_qrc.options_flow.discovery.validate_mapping",
        AsyncMock(return_value=["writability_unverified"]),
    ):
        await flow.async_step_edit_entity({"entity": "0"})
        result = await flow.async_step_settings({"name": "Updated"})
        assert result["step_id"] == "review"
        await flow.async_step_review({})
        assert entry.options["mappings"][0]["imported_from_yaml"]
        await flow.async_step_add_entity()
        flow._draft = {"platform": "number", "settings": {"control": "level"}}
        result = await flow.async_step_settings({"name": "Duplicate"})
        assert result["errors"]["base"] == "duplicate_entity"


@pytest.mark.asyncio
async def test_yaml_import_preview_atomic_confirmation_and_retry():
    mapping = {
        "platform": "number",
        "settings": {
            "component": "gain",
            "control": "level",
            "min": -80,
            "max": 10,
            "change_template": "{{ value * 2 }}",
        },
    }
    flow, entry = flow_for(
        [], [{"source": "yaml", "effective": True, "mapping": mapping}]
    )
    with patch(
        "custom_components.qsys_qrc.options_flow.discovery.validate_mapping",
        AsyncMock(return_value=[]),
    ):
        result = await flow.async_step_import_yaml({"all": True, "existing": "skip"})
        assert result["step_id"] == "yaml_review"
        assert "{{ value * 2 }}" in result["description_placeholders"]["preview"]
        assert not entry.options["mappings"]
        result = await flow.async_step_yaml_review({"confirm": True})
        assert result["step_id"] == "yaml_cleanup"
        imported = entry.options["mappings"][0]
        assert imported["imported_from_yaml"]
        assert imported["settings"]["min"] == -80
        assert imported["yaml_snapshot"]["max"] == 10
        assert flow.hass.config_entries.async_update_entry.call_count == 1
        await flow.async_step_import_yaml({"all": True, "existing": "skip"})
        assert flow._transfer["selected"] == []
        await flow.async_step_yaml_review({"confirm": True})
        assert len(entry.options["mappings"]) == 1


@pytest.mark.asyncio
async def test_yaml_import_outage_does_not_save():
    from custom_components.qsys_qrc.discovery import DiscoveryError

    mapping = {"platform": "switch", "settings": {"control": "mute"}}
    flow, entry = flow_for(
        [], [{"source": "yaml", "effective": True, "mapping": mapping}]
    )
    with patch(
        "custom_components.qsys_qrc.options_flow.discovery.validate_mapping",
        AsyncMock(side_effect=DiscoveryError()),
    ):
        result = await flow.async_step_import_yaml({"all": True, "existing": "skip"})
    assert result["errors"]["base"] == "discovery_failed"
    flow.hass.config_entries.async_update_entry.assert_not_called()
    assert not entry.options["mappings"]


@pytest.mark.asyncio
async def test_portable_import_previews_collision_and_new_ids():
    import json
    from custom_components.qsys_qrc.portable import export_document

    mapping = {"platform": "switch", "settings": {"control": "mute"}}
    flow, entry = flow_for([mapping])
    with patch(
        "custom_components.qsys_qrc.options_flow.discovery.validate_mapping",
        AsyncMock(return_value=["missing_control"]),
    ):
        result = await flow.async_step_import_portable(
            {
                "document": json.dumps(export_document("other_core", [mapping])),
                "collision": "skip",
                "transfer_yaml": False,
            }
        )
    assert result["step_id"] == "portable_review"
    assert "different name" in result["description_placeholders"]["identity_notice"]
    assert "missing_control" in result["description_placeholders"]["preview"]
    assert flow._transfer["changes"][0]["action"] == "skip"
    flow.hass.config_entries.async_update_entry.assert_not_called()
    await flow.async_step_portable_review({"confirm": True})
    assert len(entry.options["mappings"]) == 1


@pytest.mark.asyncio
async def test_flow_manager_accepts_component_menu_and_following_steps():
    from tests.flow_manager import TestFlowManager

    flow, _ = flow_for()
    manager = TestFlowManager(flow.hass)
    manager._progress[flow.flow_id] = flow
    with (
        patch(
            "custom_components.qsys_qrc.options_flow.discovery.components",
            AsyncMock(return_value=[{"Name": "gain", "Type": "gain"}]),
        ),
        patch(
            "custom_components.qsys_qrc.options_flow.discovery.controls",
            AsyncMock(
                return_value=[
                    {"Name": "mute", "Type": "Boolean", "Direction": "Read/Write"}
                ]
            ),
        ),
    ):
        result = await manager._async_handle_step(
            flow, "component", {"component": "gain"}
        )
        assert result["step_id"] == "component_kind"
        result = await manager._async_handle_step(flow, "component_kind", None)
        assert result["menu_options"] == ["control", "media_player"]
        result = await manager._async_handle_step(flow, "control", {"control": "mute"})
        assert result["step_id"] == "entity_type"
        result = await manager._async_handle_step(
            flow, "entity_type", {"platform": "switch"}
        )
        assert result["step_id"] == "settings"
        result = await manager._async_handle_step(flow, "media_player", None)
        assert result["step_id"] == "settings"


@pytest.mark.parametrize(
    "platform", ["switch", "number", "sensor", "text", "select", "media_player"]
)
def test_settings_forms_serialize_for_home_assistant_frontend(platform):
    from homeassistant.helpers import config_validation as cv
    from probatio import to_field_list
    from custom_components.qsys_qrc.mapping import normalize_mapping
    import voluptuous as vol

    flow, _ = flow_for()
    settings = {"component": "example"}
    if platform != "media_player":
        settings["control"] = "value"
    flow._draft = normalize_mapping({"platform": platform, "settings": settings})
    fields = to_field_list(
        vol.Schema(flow._settings_fields()), custom_serializer=cv.custom_serializer
    )
    assert {field["name"] for field in fields} == set(flow._draft["settings"]) - {
        "component",
        "control",
    }


@pytest.mark.asyncio
async def test_review_does_not_overwrite_concurrent_mapping_change():
    mapping = {"platform": "switch", "settings": {"control": "mute"}}
    flow, entry = flow_for([mapping])
    with patch(
        "custom_components.qsys_qrc.options_flow.discovery.validate_mapping",
        AsyncMock(return_value=[]),
    ):
        await flow.async_step_edit_entity({"entity": "0"})
        await flow.async_step_settings({"name": "Reviewed"})
    entry.options = {"mappings": [{**mapping, "settings": {"control": "other"}}]}
    result = await flow.async_step_review({})
    assert result["errors"]["base"] == "configuration_changed"
    flow.hass.config_entries.async_update_entry.assert_not_called()
    assert entry.options["mappings"][0]["settings"]["control"] == "other"


@pytest.mark.asyncio
async def test_portable_collision_choices_are_individual_and_repreviewed():
    import json
    from custom_components.qsys_qrc.portable import export_document

    mappings = [
        {"platform": "switch", "settings": {"control": name, "name": "old"}}
        for name in ("first", "second")
    ]
    incoming = [
        {"platform": "switch", "settings": {"control": name, "name": "new"}}
        for name in ("first", "second")
    ]
    flow, entry = flow_for(mappings)
    with patch(
        "custom_components.qsys_qrc.options_flow.discovery.validate_mapping",
        AsyncMock(return_value=[]),
    ):
        await flow.async_step_import_portable(
            {
                "document": json.dumps(export_document("core", incoming)),
                "collision": "skip",
                "transfer_yaml": False,
            }
        )
    result = await flow.async_step_portable_review(
        {"replace_collisions": ["0"], "confirm": True}
    )
    assert result["step_id"] == "portable_review"
    flow.hass.config_entries.async_update_entry.assert_not_called()
    assert '"replace": 1' in result["description_placeholders"]["preview"]
    await flow.async_step_portable_review({"confirm": True})
    assert entry.options["mappings"][0]["settings"]["name"] == "new"
    assert entry.options["mappings"][1]["settings"]["name"] == "old"


def test_inventory_uses_current_ui_options_during_reload():
    yaml = {"platform": "switch", "settings": {"control": "mute", "name": "YAML"}}
    flow, entry = flow_for([], [{"source": "yaml", "effective": True, "mapping": yaml}])
    assert flow._inventory()[0]["source"] == "yaml"
    entry.options = {"mappings": [{**yaml, "imported_from_yaml": True}]}
    flow.hass.data[DOMAIN][CONF_ENTRY_INVENTORY].pop("entry")
    inventory = flow._inventory()
    assert inventory[0]["source"] == "ui"
    assert inventory[0]["cleanup_pending"]
    assert not inventory[1]["effective"]


@pytest.mark.asyncio
async def test_invalid_yaml_selection_is_not_silently_dropped():
    mapping = {"platform": "switch", "settings": {"control": "mute"}}
    flow, _ = flow_for([], [{"source": "yaml", "effective": True, "mapping": mapping}])
    result = await flow.async_step_import_yaml(
        {"entities": ["0", "9"], "existing": "skip"}
    )
    assert result["errors"]["base"] == "invalid_selection"
    flow.hass.config_entries.async_update_entry.assert_not_called()
