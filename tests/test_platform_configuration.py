"""Platform setup uses effective mappings and preserves migrated registry identities."""

import asyncio
from importlib import import_module
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from custom_components.qsys_qrc.mapping import normalize_mapping, resolve_configuration
from custom_components.qsys_qrc.const import *


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "platform",
    ["switch", "number", "sensor", "binary_sensor", "text", "select", "media_player"],
)
async def test_migration_setup_preserves_entity_and_registry_identity(platform):
    module = import_module(f"custom_components.qsys_qrc.{platform}")
    settings = {"component": "gain", "name": "Example"}
    if platform != "media_player":
        settings["control"] = "value"
    mapping = normalize_mapping({"platform": platform, "settings": settings})
    expected = "core_gain" if platform == "media_player" else "core_gain_value"
    callbacks = []
    entry = SimpleNamespace(
        entry_id="entry",
        data={CONF_USER_DATA: {CONF_CORE_NAME: "core"}},
        async_on_unload=callbacks.append,
    )
    core = Mock()
    core.component.return_value.get_components = AsyncMock(
        return_value={"result": [{"Name": "gain", "Type": "gain"}]}
    )
    core.component.return_value.get_controls = AsyncMock(
        return_value={"result": {"Controls": [{"Name": "value"}]}}
    )
    core.status_get = AsyncMock(side_effect=lambda: asyncio.Event().wait())
    poller = Mock(subscribe_component_control_changes=AsyncMock())
    hass = SimpleNamespace(
        data={
            DOMAIN: {
                CONF_CACHED_CORES: {"core": core},
                CONF_ENTRY_POLLERS: {"entry": poller},
                CONF_ENTRY_CONFIG: {},
            }
        }
    )
    registry = Mock()
    existing = SimpleNamespace(
        domain=platform, unique_id=expected, entity_id=f"{platform}.example"
    )
    old = SimpleNamespace(
        domain=platform, unique_id="removed_identity", entity_id=f"{platform}.old"
    )
    device_registry = Mock()
    device_registry.async_get_device_by_identifier.return_value = SimpleNamespace(
        identifiers={(DOMAIN, "core")}
    )
    phases = [
        ({"platforms": {platform: [settings]}}, {}),
        (
            {"platforms": {platform: [settings]}},
            {"mappings": [{**mapping, "imported_from_yaml": True}]},
        ),
        ({}, {"mappings": [{**mapping, "imported_from_yaml": True}]}),
    ]
    for yaml, options in phases:
        config, _ = resolve_configuration("core", yaml, options)
        hass.data[DOMAIN][CONF_ENTRY_CONFIG]["entry"] = config
        added = []
        with (
            patch(
                "custom_components.qsys_qrc.common.device_registry.async_get",
                return_value=device_registry,
            ),
            patch.object(module.er, "async_get", return_value=registry),
            patch.object(
                module.er,
                "async_entries_for_config_entry",
                return_value=[existing, old],
            ),
        ):
            await module.async_setup_entry(hass, entry, added.extend)
        entity = next(item for item in added if item.unique_id == expected)
        assert entity.name == "Example"
        registry.async_remove.assert_called_once_with(f"{platform}.old")
        registry.reset_mock()
        for callback in callbacks:
            callback()
        callbacks.clear()
        await asyncio.sleep(0)
    assert poller.subscribe_component_control_changes.await_count >= 3
