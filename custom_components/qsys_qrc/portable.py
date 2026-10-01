"""Transport-independent portable entity definitions, excluding connection data."""

import json
import yaml

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


class PortableLoader(yaml.SafeLoader):
    """Reject aliases and duplicate keys rather than silently changing mappings."""

    def compose_node(self, parent, index):
        if self.check_event(yaml.AliasEvent):
            raise vol.Invalid("YAML aliases are not supported")
        return super().compose_node(parent, index)

    def construct_mapping(self, node, deep=False):
        pairs = [
            (
                self.construct_object(key, deep=deep),
                self.construct_object(value, deep=deep),
            )
            for key, value in node.value
        ]
        return _object(pairs)


class PortableDumper(yaml.SafeDumper):
    """Indent sequence entries as well as mapping entries by two spaces."""

    def increase_indent(self, flow=False, indentless=False):
        return super().increase_indent(flow, indentless=False)


def dump_document(document, indent=2):
    """Render portable YAML with two-space indentation."""
    return yaml.dump(
        document,
        Dumper=PortableDumper,
        indent=indent,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
    )


def parse_document(text, core_name):
    """Strictly parse a size-limited YAML or legacy JSON document for an already selected Core."""
    if not isinstance(text, str) or len(text.encode("utf-8")) > MAX_DOCUMENT_BYTES:
        raise vol.Invalid("Portable document exceeds size limit")
    try:
        if text.lstrip().startswith("{"):
            document = json.loads(
                text, object_pairs_hook=_object, parse_constant=_constant
            )
        else:
            document = yaml.load(text, Loader=PortableLoader)
    except (ValueError, TypeError, RecursionError, yaml.YAMLError) as err:
        raise vol.Invalid("Invalid portable document") from err
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
    try:
        document["mappings"] = normalize_mappings(mappings, core_name)
    except (TypeError, ValueError) as err:
        raise vol.Invalid("Invalid mapping values") from err
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
    text = dump_document(document)
    # Keep every exported document importable under the same strict rules.
    parse_document(text, core_name)
    return document
