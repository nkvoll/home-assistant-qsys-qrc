"""Panel ownership, atomic review, and wire capture regression tests."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
import voluptuous as vol

from custom_components.qsys_qrc import panel
from custom_components.qsys_qrc.qsys.qrc import Core
from custom_components.qsys_qrc.mapping import identity


def mapping(control="mute", platform="switch", **settings):
    return {"platform": platform, "settings": {"control": control, **settings}}


def test_batch_delete_warns_about_yaml_reactivation():
    item = mapping()
    result, changes = panel.build_changes(
        "core",
        [item],
        [item],
        {"operation": "delete", "identities": [identity("core", item)]},
    )
    assert result == []
    assert "reactivates" in changes[0]["warning"]


def test_bulk_edit_is_atomic_and_preserves_ownership():
    item = mapping(platform="number", min=0, max=10)
    item["imported_from_yaml"] = True
    item["yaml_snapshot"] = dict(item["settings"])
    request = {
        "operation": "edit",
        "identities": [identity("core", item)],
        "patch": {"min": 20},
    }
    with pytest.raises(vol.Invalid):
        panel.build_changes("core", [item], [], request)
    assert item["settings"]["min"] == 0
    request["patch"] = {"max": 30}
    result, _ = panel.build_changes("core", [item], [], request)
    assert result[0]["imported_from_yaml"]
    assert result[0]["yaml_snapshot"]["max"] == 10


def test_migration_requires_explicit_selected_yaml():
    item = mapping()
    result, _ = panel.build_changes(
        "core",
        [],
        [item],
        {
            "operation": "migrate",
            "collision": "replace",
            "identities": [identity("core", item)],
        },
    )
    assert result[0]["imported_from_yaml"]
    with pytest.raises(vol.Invalid):
        panel.build_changes(
            "core",
            [],
            [item],
            {
                "operation": "edit",
                "identities": [identity("core", item)],
                "patch": {"name": "New"},
            },
        )


def test_capture_is_bounded_redacted_and_detached():
    core = Core("example")
    data = {
        "method": "Logon",
        "params": {"User": "admin", "Password": "secret"},
        "id": 1,
    }
    core.capture_frame("sent", data)
    assert not core.protocol_frames
    core.protocol_capture = True
    core.capture_frame("sent", data)
    assert core.protocol_frames[0]["payload"]["params"] == {
        "User": "[redacted]",
        "Password": "[redacted]",
    }
    assert data["params"]["Password"] == "secret"
    for index in range(600):
        core.capture_frame("received", {"id": index, "result": index})
    assert len(core.protocol_frames) == 500
    assert core.protocol_frames[-1]["sequence"] == 601
    core.capture_frame("received", {"result": "a" * 40000})
    assert core.protocol_frames[-1]["payload"]["truncated"]


@pytest.mark.asyncio
async def test_review_rejects_stale_commit_and_updates_once():
    entry = SimpleNamespace(options={}, entry_id="first")
    hass = SimpleNamespace(config_entries=SimpleNamespace(async_update_entry=Mock()))
    context = AsyncMock(return_value=(entry, "core", {}, [], object()))
    request = {"operation": "create", "entry_id": "first", "mappings": [mapping()]}
    with (
        patch.object(panel, "context", context),
        patch.object(panel.discovery, "validate_mapping", AsyncMock(return_value=[])),
    ):
        review = await panel.dispatch(hass, request)
        commit = {
            **request,
            "commit": True,
            "revision": review["revision"],
            "review_token": review["review_token"],
        }
        entry.options = {"changed": True}
        with pytest.raises(vol.Invalid, match="review"):
            await panel.dispatch(hass, commit)
        hass.config_entries.async_update_entry.assert_not_called()
        entry.options = {}
        await panel.dispatch(hass, commit)
        hass.config_entries.async_update_entry.assert_called_once()


@pytest.mark.asyncio
async def test_edit_during_discovery_cannot_be_overwritten():
    entry = SimpleNamespace(options={}, entry_id="first")
    hass = SimpleNamespace(config_entries=SimpleNamespace(async_update_entry=Mock()))

    async def changed(core, mapping):
        entry.options = {"other": "change"}
        return []

    request = {
        "operation": "create",
        "entry_id": "first",
        "mappings": [mapping()],
        "commit": True,
    }
    with (
        patch.object(
            panel, "context", AsyncMock(return_value=(entry, "core", {}, [], object()))
        ),
        patch.object(panel.discovery, "validate_mapping", changed),
    ):
        with pytest.raises(vol.Invalid, match="Configuration changed"):
            await panel.dispatch(hass, request)
        hass.config_entries.async_update_entry.assert_not_called()


def test_panel_requires_admin():
    """Protocol values and configuration APIs must not be exposed to non-admins."""
    from homeassistant.exceptions import Unauthorized

    connection = SimpleNamespace(user=SimpleNamespace(is_admin=False))
    with pytest.raises(Unauthorized):
        panel.websocket_panel(None, connection, {"id": 1, "operation": "overview"})


@pytest.mark.asyncio
async def test_capture_hooks_cover_actual_sent_frames_and_notifications():
    """Observe the wire path, including frames without request IDs."""
    import asyncio
    import json
    from custom_components.qsys_qrc.qsys.qrc import ConnectionState

    core = Core("example")
    core.protocol_capture = True
    core._writer = Mock()
    await core._set_state(ConnectionState.CONNECTED)
    await core._send({"method": "NoOp", "id": 5})
    assert core.protocol_frames[0]["direction"] == "sent"
    assert core.protocol_frames[0]["payload"]["jsonrpc"] == "2.0"
    reader = asyncio.StreamReader()
    core._reader = reader
    reader.feed_data(
        json.dumps({"method": "EngineStatus", "params": {"State": "Active"}}).encode()
        + b"\0"
    )
    reader.feed_eof()
    with pytest.raises(asyncio.IncompleteReadError):
        await core._read_forever()
    assert core.protocol_frames[-1]["method"] == "EngineStatus"
    assert core.protocol_frames[-1]["direction"] == "received"


def test_migration_skip_policy_only_skips_existing_ui_copies():
    """A selected YAML definition is the source to migrate, not a collision."""
    first, second = mapping("first"), mapping("second")
    result, changes = panel.build_changes(
        "core",
        [first],
        [first, second],
        {
            "operation": "migrate",
            "collision": "skip",
            "identities": [identity("core", first), identity("core", second)],
        },
    )
    assert changes[0]["action"] == "skip"
    assert changes[1]["action"] == "add"
    assert result[1]["imported_from_yaml"]
