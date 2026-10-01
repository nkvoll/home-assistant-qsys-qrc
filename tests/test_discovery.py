"""Read-only discovery, failures, and compatibility coverage."""

import asyncio
from unittest.mock import AsyncMock, Mock

import pytest

from custom_components.qsys_qrc.discovery import (
    DiscoveryError,
    compatible_platforms,
    components,
    controls,
    named_control,
    suggested_settings,
    validate_mapping,
)


@pytest.mark.parametrize(
    ("metadata", "expected"),
    [
        ({"Type": "Boolean", "Direction": "Read/Write"}, ["sensor", "switch"]),
        ({"Type": "Float", "Direction": "Read Only"}, ["sensor"]),
        ({"Value": 1.2}, ["sensor", "number"]),
        ({"Value": True}, ["sensor", "switch"]),
        ({"Type": "String", "Choices": ["A", "B"]}, ["sensor", "text", "select"]),
        ({"Value": "A", "Direction": "Read Only", "Choices": ["A"]}, ["sensor"]),
    ],
)
def test_compatibility(metadata, expected):
    assert compatible_platforms(metadata) == expected


def test_metadata_defaults():
    settings = suggested_settings(
        "number",
        "gain",
        {"Name": "level", "ValueMin": -80, "ValueMax": 12, "Step": 0.5, "Units": "dB"},
    )
    assert settings["min"] == -80
    assert settings["max"] == 12
    assert settings["step"] == 0.5
    assert settings["unit_of_measurement"] == "dB"
    assert (
        suggested_settings("sensor", None, {"Name": "status", "Value": 0})["attribute"]
        == "Value"
    )


@pytest.mark.asyncio
async def test_discovery_and_validation_never_write():
    component_api = Mock(
        get_components=AsyncMock(
            return_value={"result": [{"Name": "gain", "Type": "gain"}]}
        ),
        get_controls=AsyncMock(
            return_value={
                "result": {
                    "Controls": [
                        {"Name": "mute", "Type": "Boolean", "Direction": "Read Only"}
                    ]
                }
            }
        ),
    )
    control_api = Mock(
        get=AsyncMock(return_value={"result": [{"Name": "named", "Value": 2}]})
    )
    core = Mock(
        component=Mock(return_value=component_api),
        control=Mock(return_value=control_api),
    )
    assert len(await components(core)) == 1
    assert len(await controls(core, "gain")) == 1
    assert (await named_control(core, "named"))["Value"] == 2
    assert await validate_mapping(
        core,
        {"platform": "switch", "settings": {"component": "gain", "control": "mute"}},
    ) == ["read_only_mismatch"]
    assert await validate_mapping(
        core,
        {"platform": "number", "settings": {"component": None, "control": "named"}},
    ) == ["writability_unverified"]
    assert (
        await validate_mapping(
            core, {"platform": "media_player", "settings": {"component": "gain"}}
        )
        == []
    )
    component_api.set.assert_not_called()
    control_api.set.assert_not_called()


@pytest.mark.asyncio
async def test_missing_and_malformed_response():
    core = Mock()
    core.control.return_value.get = AsyncMock(return_value={"result": []})
    with pytest.raises(DiscoveryError):
        await named_control(core, "absent")
    core.component.return_value.get_components = AsyncMock(return_value={"result": {}})
    with pytest.raises(DiscoveryError):
        await components(core)


@pytest.mark.asyncio
async def test_timeout_and_cancellation():
    async def slow():
        await asyncio.sleep(10)

    core = Mock()
    core.component.return_value.get_components = slow
    with pytest.raises(DiscoveryError):
        await components(core, timeout=0.001)
    task = asyncio.create_task(components(core))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_empty_media_platform_does_not_discover():
    from types import SimpleNamespace
    from unittest.mock import patch
    from custom_components.qsys_qrc import media_player
    from custom_components.qsys_qrc.const import (
        DOMAIN,
        CONF_CACHED_CORES,
        CONF_USER_DATA,
        CONF_CORE_NAME,
        CONF_ENTRY_CONFIG,
        CONF_ENTRY_POLLERS,
    )

    core = Mock()
    entry = SimpleNamespace(
        entry_id="entry", data={CONF_USER_DATA: {CONF_CORE_NAME: "core"}}
    )
    hass = SimpleNamespace(
        data={
            DOMAIN: {
                CONF_CACHED_CORES: {"core": core},
                CONF_ENTRY_CONFIG: {"entry": {"platforms": {}}},
                CONF_ENTRY_POLLERS: {"entry": Mock()},
            }
        }
    )
    add = Mock()
    with (
        patch.object(media_player.er, "async_get"),
        patch.object(
            media_player.er, "async_entries_for_config_entry", return_value=[]
        ),
    ):
        await media_player.async_setup_entry(hass, entry, add)
    core.component.assert_not_called()
    add.assert_not_called()


@pytest.mark.asyncio
async def test_import_preview_reports_missing_component():
    core = Mock()
    core.component.return_value.get_components = AsyncMock(return_value={"result": []})
    assert await validate_mapping(
        core,
        {"platform": "number", "settings": {"component": "removed", "control": "gain"}},
    ) == ["missing_component"]
    core.component.return_value.get_controls.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("kind", "issues"),
    [
        ("gain", []),
        ("URL_receiver", []),
        ("audio_file_player", []),
        ("unsupported", ["unsupported_component_type"]),
    ],
)
async def test_media_component_compatibility(kind, issues):
    core = Mock()
    core.component.return_value.get_components = AsyncMock(
        return_value={"result": [{"Name": "player", "Type": kind}]}
    )
    assert (
        await validate_mapping(
            core, {"platform": "media_player", "settings": {"component": "player"}}
        )
        == issues
    )
    core.component.return_value.set.assert_not_called()
