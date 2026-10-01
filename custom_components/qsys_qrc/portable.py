"""Transport-independent portable entity definitions, excluding connection data."""

import json

import voluptuous as vol

from .mapping import MAPPING_VERSION, normalize_mappings

MAX_DOCUMENT_BYTES = 262144
MAX_MAPPINGS = 1000


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise vol.Invalid("Duplicate JSON key")
        result[key] = value
    return result


def _constant(value):
    raise vol.Invalid("Non-finite JSON number")


def parse_document(text, core_name):
    """Strictly parse a size-limited JSON document for an already selected Core."""
    if not isinstance(text, str) or len(text.encode("utf-8")) > MAX_DOCUMENT_BYTES:
        raise vol.Invalid("Portable document exceeds size limit")
    try:
        document = json.loads(text, object_pairs_hook=_object, parse_constant=_constant)
    except (ValueError, RecursionError) as err:
        raise vol.Invalid("Invalid JSON document") from err
    if not isinstance(document, dict) or set(document) - {
        "version",
        "core_name",
        "design_name",
        "mappings",
    }:
        raise vol.Invalid("Invalid document fields")
    if (
        type(document.get("version")) is not int
        or document["version"] != MAPPING_VERSION
    ):
        raise vol.Invalid("Unsupported document version")
    if not isinstance(document.get("core_name"), str) or not document["core_name"]:
        raise vol.Invalid("Missing source Core name")
    if "design_name" in document and not isinstance(document["design_name"], str):
        raise vol.Invalid("Invalid design name")
    mappings = document.get("mappings")
    if not isinstance(mappings, list) or len(mappings) > MAX_MAPPINGS:
        raise vol.Invalid("Invalid mapping count")
    for mapping in mappings:
        if not isinstance(mapping, dict) or set(mapping) != {"platform", "settings"}:
            raise vol.Invalid("Portable mappings cannot carry ownership metadata")
    document["mappings"] = normalize_mappings(mappings, core_name)
    return document


def export_document(core_name, mappings, design_name=None):
    """Export only reviewed entity settings, never entry or connection identifiers."""
    mappings = normalize_mappings(mappings, core_name)
    document = {
        "version": MAPPING_VERSION,
        "core_name": core_name,
        "mappings": [
            {"platform": mapping["platform"], "settings": mapping["settings"]}
            for mapping in mappings
        ],
    }
    if design_name is not None:
        document["design_name"] = design_name
    text = json.dumps(document, indent=2, allow_nan=False)
    # Keep every exported document importable under the same strict rules.
    parse_document(text, core_name)
    return document
