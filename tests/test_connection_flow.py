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
