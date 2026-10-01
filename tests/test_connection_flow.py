"""Connection validation and lifecycle flow tests."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from custom_components.qsys_qrc.config_flow import (
    ConfigFlow,
    InvalidAuth,
    validate_input,
)
from custom_components.qsys_qrc.const import *

DATA = {
    CONF_CORE_NAME: "core",
    CONF_HOST: "example.test",
    CONF_PORT: 1711,
    CONF_USERNAME: "user",
    CONF_PASSWORD: "secret",
}


@pytest.fixture(autouse=True)
def mock_yaml_config():
    with patch(
        "custom_components.qsys_qrc.config_flow.async_integration_yaml_config",
        AsyncMock(return_value={}),
    ):
        yield


@pytest.mark.parametrize("field", [CONF_POLL_INTERVAL, CONF_REQUEST_TIMEOUT])
@pytest.mark.parametrize("value", [0, -1, float("inf"), float("nan"), "invalid"])
def test_invalid_polling_durations(field, value):
    import voluptuous as vol
    from custom_components.qsys_qrc.config_flow import STEP_USER_DATA_SCHEMA

    with pytest.raises(vol.Invalid):
        STEP_USER_DATA_SCHEMA({**DATA, field: value})


@pytest.mark.asyncio
@pytest.mark.parametrize("step", ["user", "reconfigure", "reauth_confirm"])
async def test_polling_settings_copy_yaml_and_save(step):
    flow = ConfigFlow()
    flow.hass = Mock()
    flow._async_current_entries = Mock(return_value=[])
    flow.async_set_unique_id = AsyncMock()
    flow._abort_if_unique_id_configured = Mock()
    flow.async_update_reload_and_abort = Mock(return_value={"type": "abort"})
    entry = None if step == "user" else SimpleNamespace(
        entry_id="old", unique_id="core", data={CONF_USER_DATA: DATA}, options={}
    )
    async def validate(hass, submitted):
        return {CONF_USER_DATA: submitted, CONF_ENGINE_STATUS: {}}

    with (
        patch(
            "custom_components.qsys_qrc.config_flow.async_integration_yaml_config",
            AsyncMock(return_value={DOMAIN: {CONF_CORES: {"core": {
                CONF_CHANGEGROUP: {CONF_POLL_INTERVAL: 2.5, CONF_REQUEST_TIMEOUT: 8.0}
            }}}}),
        ),
        patch("custom_components.qsys_qrc.config_flow.validate_input", side_effect=validate),
    ):
        await flow._connection_step(step, DATA, entry)
    saved = flow._initial_entry.data if entry is None else flow.async_update_reload_and_abort.call_args.kwargs["data"]
    assert saved[CONF_USER_DATA][CONF_POLL_INTERVAL] == 2.5
    assert saved[CONF_USER_DATA][CONF_REQUEST_TIMEOUT] == 8.0


@pytest.mark.asyncio
async def test_reconfigure_changes_saved_polling_settings():
    flow = ConfigFlow()
    flow.hass = Mock()
    flow._async_current_entries = Mock(return_value=[])
    flow.async_update_reload_and_abort = Mock(return_value={"type": "abort"})
    entry = SimpleNamespace(entry_id="old", unique_id="core", options={}, data={
        CONF_USER_DATA: {**DATA, CONF_POLL_INTERVAL: 2.5, CONF_REQUEST_TIMEOUT: 8.0}
    })
    async def validate(hass, submitted):
        return {CONF_USER_DATA: submitted, CONF_ENGINE_STATUS: {}}

    with patch("custom_components.qsys_qrc.config_flow.validate_input", side_effect=validate):
        await flow._connection_step("reconfigure", {CONF_POLL_INTERVAL: 0.5}, entry)
    saved = flow.async_update_reload_and_abort.call_args.kwargs["data"][CONF_USER_DATA]
    assert saved[CONF_POLL_INTERVAL] == 0.5
    assert saved[CONF_REQUEST_TIMEOUT] == 8.0


@pytest.mark.asyncio
@pytest.mark.parametrize("authorized", [True, False])
async def test_validation_always_awaits_shutdown(authorized):
    cleaned = asyncio.Event()
    started = asyncio.Event()

    async def run():
        try:
            started.set()
            await asyncio.Event().wait()
        finally:
            cleaned.set()

    core = Mock(
        run_until_stopped=run,
        wait_until_running=started.wait,
        logon=AsyncMock(return_value={"result": authorized}),
        status_get=AsyncMock(return_value={"result": {"DesignName": "Example"}}),
    )
    with patch(
        "custom_components.qsys_qrc.config_flow.qrc.Core", return_value=core
    ) as constructor:
        if authorized:
            result = await validate_input(None, DATA)
            assert result[CONF_USER_DATA] == DATA
        else:
            with pytest.raises(InvalidAuth):
                await validate_input(None, DATA)
        constructor.assert_called_once_with("example.test", 1711)
    assert cleaned.is_set()


def test_duplicates_include_unloaded_legacy_entries():
    flow = ConfigFlow()
    flow._async_current_entries = Mock(
        return_value=[SimpleNamespace(entry_id="old", data={CONF_USER_DATA: DATA})]
    )
    assert flow._duplicate({**DATA, CONF_HOST: "other.test"})
    assert flow._duplicate({**DATA, CONF_CORE_NAME: "other"})
    assert not flow._duplicate(DATA, entry_id="old")
    assert not flow._duplicate(
        {**DATA, CONF_CORE_NAME: "other", CONF_HOST: "other.test"}
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("step", ["reconfigure", "reauth_confirm"])
async def test_reconnection_preserves_core_name_options_and_identity(step):
    flow = ConfigFlow()
    flow.hass = Mock()
    flow._async_current_entries = Mock(return_value=[])
    flow.async_update_reload_and_abort = Mock(return_value={"type": "abort"})
    entry = SimpleNamespace(
        entry_id="old",
        unique_id=None,
        data={CONF_USER_DATA: DATA},
        options={"mappings": [{"platform": "switch"}]},
    )
    with patch(
        "custom_components.qsys_qrc.config_flow.validate_input",
        AsyncMock(return_value={CONF_USER_DATA: DATA, CONF_ENGINE_STATUS: {}}),
    ) as validate:
        await flow._connection_step(step, {**DATA, CONF_CORE_NAME: "changed"}, entry)
    assert validate.call_args.args[1][CONF_CORE_NAME] == "core"
    kwargs = flow.async_update_reload_and_abort.call_args.kwargs
    assert kwargs["unique_id"] == "core"
    assert "options" not in kwargs


@pytest.mark.asyncio
async def test_initial_setup_offers_empty_core_or_assisted_entity():
    flow = ConfigFlow()
    flow.hass = Mock()
    flow._async_current_entries = Mock(return_value=[])
    flow.async_set_unique_id = AsyncMock()
    flow._abort_if_unique_id_configured = Mock()
    with (
        patch(
            "custom_components.qsys_qrc.config_flow.validate_input",
            AsyncMock(
                return_value={
                    CONF_USER_DATA: DATA,
                    CONF_ENGINE_STATUS: {"DesignName": "Example"},
                }
            ),
        ),
        patch(
            "custom_components.qsys_qrc.config_flow.async_integration_yaml_config",
            AsyncMock(return_value={}),
        ),
    ):
        result = await flow.async_step_user(DATA)
    assert result["step_id"] == "setup_entities"
    assert result["menu_options"] == ["add_entity", "finish"]
    empty = await flow.async_step_finish()
    assert empty["options"] == {}
    with (
        patch(
            "custom_components.qsys_qrc.options_flow.discovery.named_control",
            AsyncMock(return_value={"Name": "mute", "Value": True}),
        ),
        patch(
            "custom_components.qsys_qrc.options_flow.discovery.validate_mapping",
            AsyncMock(return_value=["writability_unverified"]),
        ),
    ):
        await flow.async_step_add_entity()
        await flow.async_step_named_control({"control": "mute"})
        await flow.async_step_entity_type({"platform": "switch"})
        await flow.async_step_settings({"name": "Mute"})
        result = await flow.async_step_review({})
    assert result["step_id"] == "setup_entities"
    saved = await flow.async_step_finish()
    assert saved["options"]["mappings"][0]["settings"]["name"] == "Mute"
    flow.hass.config_entries.async_update_entry.assert_not_called()


@pytest.mark.asyncio
async def test_flow_manager_accepts_initial_entity_menu():
    from tests.flow_manager import TestFlowManager

    flow = ConfigFlow()
    flow.hass = Mock()
    manager = TestFlowManager(flow.hass)
    manager._progress[flow.flow_id] = flow
    result = await manager._async_handle_step(flow, "init", None)
    assert result["step_id"] == "setup_entities"
    result = await manager._async_handle_step(flow, "setup_entities", None)
    assert result["menu_options"] == ["add_entity", "finish"]


@pytest.mark.asyncio
async def test_malformed_status_does_not_create_connection():
    from custom_components.qsys_qrc.config_flow import CannotConnect

    started = asyncio.Event()
    stopped = asyncio.Event()

    async def run():
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    core = Mock(
        run_until_stopped=run,
        wait_until_running=started.wait,
        logon=AsyncMock(return_value={"result": True}),
        status_get=AsyncMock(return_value={"result": []}),
    )
    with (
        patch("custom_components.qsys_qrc.config_flow.qrc.Core", return_value=core),
        pytest.raises(CannotConnect),
    ):
        await validate_input(None, DATA)
    assert stopped.is_set()
