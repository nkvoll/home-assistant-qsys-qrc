"""Listening-range behavior, live read-back, and unchanged legacy control paths."""

from copy import deepcopy
from unittest.mock import AsyncMock, Mock, patch

import pytest
import voluptuous as vol
from homeassistant.components.number import NumberMode
from homeassistant.exceptions import PlatformNotReady

from custom_components.qsys_qrc import media_player, number
from custom_components.qsys_qrc.discovery import validate_mapping
from custom_components.qsys_qrc.mapping import (
    identity,
    migrate_volume_options,
    normalize_mapping,
)
from custom_components.qsys_qrc.panel import build_changes
from custom_components.qsys_qrc.portable import (
    dump_document,
    export_document,
    parse_document,
)
from custom_components.qsys_qrc.schema import CONFIG_SCHEMA
from custom_components.qsys_qrc.volume import GainRange, media_gain_names

SETTINGS = {"volume_mode": "db", "min_db": -60.0, "max_db": 0.0}
LEVELS = [(0, -100), (0.01, -59.4), (0.5, -30), (0.9, -6), (1, 0)]
PLAYERS = [
    (media_player.QRCGainEntity, "gain"),
    (media_player.QRCAudioFilePlayerEntity, "audio_file_player"),
    (media_player.QRCUrlReceiverEntity, "URL_receiver"),
]


def gain(name="gain", minimum=-100, maximum=20):
    return {
        "Name": name,
        "Type": "Float",
        "Value": -30.0,
        "ValueMin": minimum,
        "ValueMax": maximum,
        "StringMin": f"{minimum}dB",
        "Direction": "Read/Write",
    }


def player(cls, kind, settings=None, metadata=None):
    """Construct the real entity with registry setup isolated."""
    with patch.object(media_player.QSysComponentBase, "__init__", return_value=None):
        entity = cls(None, None, "core", None, "unique", "Speaker", "speaker", None)
    entity.component = "speaker"
    entity.core = Mock()
    entity.core.component.return_value.set = AsyncMock()
    entity.async_write_ha_state = Mock()
    entity.configure_volume(
        settings or SETTINGS,
        kind,
        metadata or [gain(name) for name in media_gain_names(kind)],
    )
    return entity


def number_entity(gain_range=None, **overrides):
    settings = {
        "use_position": False,
        "position_lower_limit": 0,
        "position_upper_limit": 1,
        "min_value": -100,
        "max_value": 20,
        "step": 0.1,
        "mode": NumberMode.SLIDER,
        "change_template": None,
        "value_template": None,
        "device_class": None,
        "unit_of_measurement": "dB",
        **overrides,
    }
    with patch.object(number.QSysComponentControlBase, "__init__", return_value=None):
        entity = number.QRCNumberEntity(
            None,
            None,
            "core",
            None,
            "unique",
            "Gain",
            "speaker",
            "gain",
            **settings,
            gain_range=gain_range,
        )
    entity.update_control = AsyncMock()
    return entity


@pytest.mark.parametrize(("cls", "kind"), PLAYERS)
@pytest.mark.parametrize(("level", "expected"), LEVELS)
@pytest.mark.asyncio
async def test_media_set_and_external_read_back(cls, kind, level, expected):
    entity = player(cls, kind)
    api = entity.core.component.return_value
    # Setup and out-of-range external changes must never issue Set.
    for name in media_gain_names(kind):
        for value, displayed in [(-100, 0), (-70, 0), (10, 1), (expected, level)]:
            entity.on_changed(None, {"Name": name, "Value": value})
            assert entity.volume_level == pytest.approx(displayed)
    api.set.assert_not_called()
    await entity.async_set_volume_level(level)
    assert api.set.call_args.args == (
        "speaker",
        [
            {"Name": name, "Value": pytest.approx(expected)}
            for name in media_gain_names(kind)
        ],
    )
    # Volume writes never issue mute commands.
    assert all("mute" not in item["Name"] for item in api.set.call_args.args[1])


@pytest.mark.parametrize(("cls", "kind"), PLAYERS)
@pytest.mark.asyncio
async def test_media_legacy_mapping_retains_position(cls, kind):
    entity = player(cls, kind, {"volume_mode": "legacy"})
    for name in media_gain_names(kind):
        entity.on_changed(None, {"Name": name, "Value": -30, "Position": 0.4})
        assert entity.volume_level == pytest.approx(0.4 / media_player.POSITION_0DB)
    await entity.async_set_volume_level(0.5)
    assert entity.core.component.return_value.set.call_args.args[1] == [
        {"Name": name, "Position": 0.5 * media_player.POSITION_0DB}
        for name in media_gain_names(kind)
    ]


@pytest.mark.asyncio
async def test_stereo_zero_uses_each_channel_minimum():
    entity = player(
        media_player.QRCUrlReceiverEntity,
        "URL_receiver",
        metadata=[gain("channel.1.gain", -80, 6), gain("channel.2.gain", -65, 3)],
    )
    await entity.async_set_volume_level(0)
    assert entity.core.component.return_value.set.call_args.args[1] == [
        {"Name": "channel.1.gain", "Value": -80},
        {"Name": "channel.2.gain", "Value": -65},
    ]
    entity.on_changed(None, {"Name": "channel.2.mute", "Value": 1})
    assert entity.is_volume_muted


@pytest.mark.parametrize(
    "metadata",
    [
        [gain("channel.1.gain"), gain("channel.2.gain", -40, 20)],
        [gain("channel.1.gain")],
    ],
)
def test_invalid_stereo_limits_prevent_setup_without_writes(metadata):
    with pytest.raises(PlatformNotReady):
        player(media_player.QRCUrlReceiverEntity, "URL_receiver", metadata=metadata)


@pytest.mark.parametrize(("level", "expected"), LEVELS)
@pytest.mark.asyncio
async def test_number_percentage_set_and_read_back(level, expected):
    entity = number_entity(GainRange(-60, 0, -100))
    assert entity.native_min_value == 0
    assert entity.native_max_value == 100
    assert entity.native_unit_of_measurement == "%"
    await entity.on_control_changed(None, {"Value": expected})
    assert entity.native_value == pytest.approx(level * 100)
    entity.update_control.assert_not_called()
    await entity.async_set_native_value(level * 100)
    entity.update_control.assert_awaited_once_with({"Value": pytest.approx(expected)})


@pytest.mark.parametrize(
    ("value", "expected"), [(-80, 0), (-60, 0), (-30, 50), (6, 100)]
)
@pytest.mark.asyncio
async def test_number_external_gain_clamps_display_only(value, expected):
    entity = number_entity(GainRange(-60, 0, -80))
    await entity.on_control_changed(None, {"Value": value})
    assert entity.native_value == expected
    entity.update_control.assert_not_called()


@pytest.mark.asyncio
async def test_number_raw_db_and_position_templates_are_preserved():
    raw = number_entity()
    await raw.on_control_changed(None, {"Value": -30, "Position": 0.123})
    assert raw.native_value == -30
    assert raw.native_unit_of_measurement == "dB"
    await raw.async_set_native_value(-6)
    raw.update_control.assert_awaited_once_with({"Value": -6})
    positioned = number_entity(
        use_position=True, position_lower_limit=0.3, position_upper_limit=0.8
    )
    await positioned.on_control_changed(None, {"Value": -30, "Position": 0.55})
    assert positioned.native_value == 50
    await positioned.async_set_native_value(90)
    positioned.update_control.assert_awaited_once_with({"Position": 0.75})
    change = Mock(async_render=Mock(return_value=42.0))
    outgoing = Mock(async_render=Mock(return_value=-12.0))
    templated = number_entity(change_template=change, value_template=outgoing)
    await templated.on_control_changed(None, {"Value": -30})
    assert templated.native_value == 20  # Existing raw UI bounds still clamp.
    await templated.async_set_native_value(10)
    templated.update_control.assert_awaited_once_with({"Value": -12.0})


@pytest.mark.asyncio
async def test_percentage_number_templates_apply_to_percentage():
    change = Mock(async_render=Mock(return_value=45.0))
    outgoing = Mock(async_render=Mock(return_value=90.0))
    entity = number_entity(
        GainRange(-60, 0, -80), change_template=change, value_template=outgoing
    )
    await entity.on_control_changed(None, {"Value": -30})
    assert change.async_render.call_args.args[0]["value"] == 50
    assert entity.native_value == 45
    await entity.async_set_native_value(50)
    entity.update_control.assert_awaited_once_with({"Value": -6.0})


@pytest.mark.parametrize("platform", ["media_player", "number"])
@pytest.mark.parametrize(
    "bounds",
    [
        {"min_db": 0, "max_db": 0},
        {"min_db": 1, "max_db": 0},
        {"min_db": float("nan")},
        {"max_db": float("inf")},
    ],
)
def test_yaml_rejects_invalid_range(platform, bounds):
    settings = {"component": "speaker", **bounds}
    if platform == "number":
        settings["control"] = "gain"
    with pytest.raises(vol.Invalid):
        CONFIG_SCHEMA(
            {"qsys_qrc": {"cores": {"core": {"platforms": {platform: [settings]}}}}}
        )


@pytest.mark.parametrize("platform", ["media_player", "number"])
def test_old_yaml_stays_legacy_and_explicit_bounds_opt_in(platform):
    settings = {"component": "speaker"}
    if platform == "number":
        settings["control"] = "gain"
    legacy = normalize_mapping({"platform": platform, "settings": settings})
    assert legacy["settings"]["volume_mode"] == "legacy"
    configured = normalize_mapping(
        {"platform": platform, "settings": {**settings, "min_db": -60, "max_db": 0}}
    )
    assert configured["settings"]["volume_mode"] == "db"
    assert normalize_mapping(legacy) == legacy
    document = export_document(
        "core",
        [
            legacy,
            {
                **configured,
                "settings": {**configured["settings"], "component": "other"},
            },
        ],
    )
    assert parse_document(dump_document(document), "core") == document


def test_upgrade_is_idempotent_and_bulk_opt_in_is_single_edit():
    options = {
        "other_option": 42,
        "mappings": [
            {"platform": "media_player", "settings": {"component": "first"}},
            {"platform": "media_player", "settings": {"component": "second"}},
        ],
    }
    original = deepcopy(options)
    upgraded = migrate_volume_options(options)
    assert options == original
    assert upgraded["other_option"] == 42
    assert migrate_volume_options(upgraded) == upgraded
    assert all(m["settings"]["volume_mode"] == "legacy" for m in upgraded["mappings"])
    edited, _ = build_changes(
        "core",
        upgraded["mappings"],
        [],
        {
            "operation": "edit",
            "identities": [identity("core", m) for m in upgraded["mappings"]],
            "patch": SETTINGS,
        },
    )
    assert all(all(m["settings"][k] == v for k, v in SETTINGS.items()) for m in edited)
    assert [identity("core", m) for m in edited] == [
        identity("core", m) for m in upgraded["mappings"]
    ]


@pytest.mark.parametrize(
    ("metadata", "issues"),
    [
        (gain(minimum=-80, maximum=6), []),
        (gain(minimum=-40), ["gain_range_out_of_bounds"]),
        (gain(maximum=-6), ["gain_range_out_of_bounds"]),
        (
            {
                "Name": "gain",
                "Type": "Float",
                "Value": -30,
                "String": "-30dB",
                "Direction": "Read/Write",
            },
            ["gain_limits_unavailable"],
        ),
    ],
)
@pytest.mark.parametrize("platform", ["media_player", "number"])
@pytest.mark.asyncio
async def test_live_validation_uses_actual_limits(metadata, issues, platform):
    core = Mock()
    api = core.component.return_value
    api.get_components = AsyncMock(
        return_value={"result": [{"Name": "speaker", "Type": "gain"}]}
    )
    api.get_controls = AsyncMock(return_value={"result": {"Controls": [metadata]}})
    assert (
        await validate_mapping(
            core,
            {
                "platform": platform,
                "settings": {"component": "speaker", "control": "gain", **SETTINGS},
            },
        )
        == issues
    )
    api.set.assert_not_called()


@pytest.mark.asyncio
async def test_media_volume_service_targets_multiple_speakers(hass):
    """Use the same normalized HA service volume for differently bounded speakers."""
    from homeassistant.components.media_player import DATA_COMPONENT
    from homeassistant.setup import async_setup_component

    assert await async_setup_component(hass, "media_player", {})
    entities = [player(media_player.QRCGainEntity, "gain") for _ in range(2)]
    for index, entity in enumerate(entities):
        entity.entity_id = f"media_player.speaker_{index}"
        entity._attr_unique_id = f"speaker_{index}"
        entity._attr_available = True
    entities[1].configure_volume(
        {**SETTINGS, "min_db": -40, "max_db": -10}, "gain", [gain(minimum=-80)]
    )
    await hass.data[DATA_COMPONENT].async_add_entities(entities)
    await hass.services.async_call(
        "media_player",
        "volume_set",
        {
            "entity_id": [entity.entity_id for entity in entities],
            "volume_level": 0.5,
        },
        blocking=True,
    )
    assert entities[0].core.component.return_value.set.call_args.args[1] == [
        {"Name": "gain", "Value": -30}
    ]
    assert entities[1].core.component.return_value.set.call_args.args[1] == [
        {"Name": "gain", "Value": -25}
    ]


@pytest.mark.parametrize("platform", ["media_player", "number"])
@pytest.mark.parametrize(
    "control",
    [
        gain(minimum=-40),
        {
            "Name": "gain",
            "Type": "Float",
            "Value": -30,
            "String": "-30dB",
            "Direction": "Read/Write",
        },
    ],
)
@pytest.mark.asyncio
async def test_panel_cannot_commit_unverified_or_out_of_bounds_range(platform, control):
    from types import SimpleNamespace
    from custom_components.qsys_qrc import panel

    entry = SimpleNamespace(options={}, entry_id="first")
    hass = SimpleNamespace(config_entries=SimpleNamespace(async_update_entry=Mock()))
    core = Mock()
    core.component.return_value.get_components = AsyncMock(
        return_value={"result": [{"Name": "speaker", "Type": "gain"}]}
    )
    core.component.return_value.get_controls = AsyncMock(
        return_value={"result": {"Controls": [control]}}
    )
    settings = {"component": "speaker", **SETTINGS}
    if platform == "number":
        settings["control"] = "gain"
    request = {
        "operation": "create",
        "entry_id": "first",
        "mappings": [{"platform": platform, "settings": settings}],
    }
    with patch.object(
        panel, "context", AsyncMock(return_value=(entry, "core", {}, [], core))
    ):
        review = await panel.dispatch(hass, request)
        assert review["findings"][0]["issues"]
        with pytest.raises(vol.Invalid, match="incompatible"):
            await panel.dispatch(
                hass,
                {
                    **request,
                    "commit": True,
                    "revision": review["revision"],
                    "review_token": review["review_token"],
                },
            )
    hass.config_entries.async_update_entry.assert_not_called()
    core.component.return_value.set.assert_not_called()


@pytest.mark.parametrize(
    ("controls", "issues"),
    [
        ([gain("channel.1.gain", -80, 6), gain("channel.2.gain", -65, 3)], []),
        (
            [gain("channel.1.gain"), gain("channel.2.gain", -40, 6)],
            ["gain_range_out_of_bounds"],
        ),
        ([gain("channel.1.gain")], ["missing_gain_control"]),
    ],
)
@pytest.mark.asyncio
async def test_live_stereo_validation_checks_both_channels(controls, issues):
    core = Mock()
    core.component.return_value.get_components = AsyncMock(
        return_value={"result": [{"Name": "stereo", "Type": "URL_receiver"}]}
    )
    core.component.return_value.get_controls = AsyncMock(
        return_value={"result": {"Controls": controls}}
    )
    assert (
        await validate_mapping(
            core,
            {
                "platform": "media_player",
                "settings": {"component": "stereo", **SETTINGS},
            },
        )
        == issues
    )
    core.component.return_value.set.assert_not_called()
