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
        result = await flow.async_step_review({"confirm": True})
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
        await flow.async_step_review({"confirm": True})
        assert entry.options["mappings"][0]["imported_from_yaml"]
        await flow.async_step_add_entity()
        flow._draft = {"platform": "number", "settings": {"control": "level"}}
        result = await flow.async_step_settings({"name": "Duplicate"})
        assert result["errors"]["base"] == "duplicate_entity"
