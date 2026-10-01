"""Portable schema strictness and credential-free round trips."""

import json
import pytest

from custom_components.qsys_qrc.portable import (
    export_document,
    parse_document,
    MAX_DOCUMENT_BYTES,
)
import voluptuous as vol

MAPPING = {
    "platform": "number",
    "settings": {
        "component": "gain",
        "control": "level",
        "min": -80,
        "max": 12,
        "change_template": "{{ value }}",
    },
}


def test_round_trip_excludes_ownership_and_identifiers():
    document = export_document(
        "source",
        [{**MAPPING, "imported_from_yaml": True, "yaml_snapshot": MAPPING["settings"]}],
        "Design",
    )
    assert set(document) == {"version", "core_name", "mappings", "design_name"}
    assert set(document["mappings"][0]) == {"platform", "settings"}
    parsed = parse_document(json.dumps(document), "target")
    assert parsed["mappings"][0]["settings"]["change_template"] == "{{ value }}"
    assert parsed["core_name"] == "source"
    for field in ("host", "port", "username", "password", "entry_id", "entity_id"):
        assert field not in document


@pytest.mark.parametrize(
    "document",
    [
        '{"version":1,"version":1}',
        '{"version":NaN}',
        json.dumps({"version": True, "core_name": "core", "mappings": []}),
        json.dumps({"version": 2, "core_name": "core", "mappings": []}),
        json.dumps(
            {"version": 1, "core_name": "core", "mappings": [], "password": "secret"}
        ),
        json.dumps(
            {
                "version": 1,
                "core_name": "core",
                "mappings": [{**MAPPING, "imported_from_yaml": True}],
            }
        ),
        json.dumps({"version": 1, "core_name": "core", "mappings": [MAPPING, MAPPING]}),
        " " * (MAX_DOCUMENT_BYTES + 1),
    ],
)
def test_reject_invalid_document(document):
    with pytest.raises(vol.Invalid):
        parse_document(document, "target")


def test_yaml_round_trip_and_two_space_sequence_indentation():
    from custom_components.qsys_qrc.portable import dump_document

    document = export_document("source", [MAPPING])
    text = dump_document(document)
    assert (
        "mappings:\n  - platform: number\n    settings:\n      component: gain" in text
    )
    assert parse_document(text, "target")["mappings"] == document["mappings"]


@pytest.mark.parametrize(
    "text",
    [
        "version: 1\nversion: 1\ncore_name: core\nmappings: []\n",
        "version: 1\ncore_name: core\nmappings: &a [*a]\n",
        "!!python/object/apply:os.system [echo unsafe]",
    ],
)
def test_yaml_rejects_duplicate_keys_aliases_and_unsafe_tags(text):
    with pytest.raises(vol.Invalid):
        parse_document(text, "target")
