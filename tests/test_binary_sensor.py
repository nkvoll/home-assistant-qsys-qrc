"""Binary sensors report Boolean state without exposing write actions."""

from unittest.mock import Mock

import pytest

from custom_components.qsys_qrc.binary_sensor import QRCBinarySensorEntity
from custom_components.qsys_qrc.discovery import compatible_platforms
from custom_components.qsys_qrc.portable import (
    export_document,
    dump_document,
    parse_document,
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (True, True),
        (False, False),
        (1, True),
        (0, False),
        (1.0, True),
        (0.0, False),
        (None, None),
        ("false", None),
        (2, None),
    ],
)
async def test_binary_state_conversion_never_writes(value, expected):
    entity = QRCBinarySensorEntity.__new__(QRCBinarySensorEntity)
    core = Mock()
    await entity.on_control_changed(core, {"Value": value})
    assert entity.is_on is expected
    assert not hasattr(entity, "async_turn_on")
    assert not hasattr(entity, "async_turn_off")
    core.assert_not_called()
    core.component.assert_not_called()
    core.control.assert_not_called()


def test_read_only_boolean_offers_binary_sensor_without_switch():
    assert compatible_platforms({"Type": "Boolean", "Direction": "Read Only"}) == [
        "binary_sensor",
        "sensor",
    ]


def test_binary_sensor_portable_yaml_round_trip():
    mapping = {
        "platform": "binary_sensor",
        "settings": {"component": "mixer", "control": "mute", "name": "Muted"},
    }
    text = dump_document(export_document("source", [mapping]))
    result = parse_document(text, "target")
    assert result["mappings"][0]["platform"] == "binary_sensor"
    assert result["mappings"][0]["settings"]["control"] == "mute"
