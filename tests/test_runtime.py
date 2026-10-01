"""Entry lifecycle isolation and shared subscription tests."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from custom_components import qsys_qrc as integration
from custom_components.qsys_qrc.const import *


@pytest.mark.asyncio
async def test_setup_reload_and_unload_preserve_device():
    callbacks = []
    entry = SimpleNamespace(
        entry_id="first",
        options={"mappings": [{"platform": "switch", "settings": {"control": "mute"}}]},
        data={
            CONF_USER_DATA: {
                CONF_CORE_NAME: "core",
                CONF_HOST: "example.test",
                CONF_PORT: 1711,
                CONF_USERNAME: "",
                CONF_PASSWORD: "",
            },
            CONF_ENGINE_STATUS: {"DesignName": "Example"},
        },
        async_on_unload=callbacks.append,
        add_update_listener=Mock(return_value=lambda: None),
    )
    hass = SimpleNamespace(
        data={DOMAIN: {CONF_CACHED_CORES: {}}},
        config_entries=SimpleNamespace(
            async_forward_entry_setups=AsyncMock(),
            async_unload_platforms=AsyncMock(return_value=True),
            async_reload=AsyncMock(),
        ),
    )
    registry = Mock()
    core = Mock(run_until_stopped=AsyncMock())
    poller = Mock(stop=AsyncMock())
    with (
        patch.object(
            integration,
            "async_integration_yaml_config",
            AsyncMock(
                return_value={
                    DOMAIN: {
                        CONF_CORES: {
                            "core": {
                                CONF_PLATFORMS: {"sensor": [{"control": "status"}]}
                            }
                        }
                    }
                }
            ),
        ),
        patch.object(integration.qrc, "Core", return_value=core) as constructor,
        patch.object(
            integration, "create_change_group_for_platform", return_value=poller
        ) as factory,
        patch.object(integration.dr, "async_get", return_value=registry),
        patch.object(integration.dr, "async_entries_for_config_entry", return_value=[]),
        patch.object(integration, "async_register_admin_service"),
    ):
        assert await integration.async_setup_entry(hass, entry)
        constructor.assert_called_once_with("example.test", 1711)
        factory.assert_called_once()
        poller.start.assert_called_once()
        effective = hass.data[DOMAIN][CONF_ENTRY_CONFIG]["first"]
        assert effective[CONF_PLATFORMS]["switch"][0][CONF_CONTROL] == "mute"
        assert effective[CONF_PLATFORMS]["sensor"][0][CONF_CONTROL] == "status"
        listener = entry.add_update_listener.call_args.args[0]
        await listener(hass, entry)
        hass.config_entries.async_reload.assert_awaited_once_with("first")
        assert await integration.async_unload_entry(hass, entry)
        poller.stop.assert_awaited_once()
        registry.async_remove_device.assert_not_called()
        assert not hass.data[DOMAIN][CONF_ENTRY_CONFIG]
    for callback in callbacks:
        callback()
    await asyncio.sleep(0)
