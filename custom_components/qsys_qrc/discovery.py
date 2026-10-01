"""Bounded, read-only QRC discovery and entity compatibility."""

import asyncio
import math

from .qsys import qrc

MEDIA_COMPONENT_TYPES = frozenset({"URL_receiver", "audio_file_player", "gain"})


class DiscoveryError(Exception):
    """Discovery failed; saved configuration must remain intact."""


class MissingControlError(DiscoveryError):
    """A successful response did not contain the requested Named Control."""


async def _request(awaitable, timeout):
    try:
        response = await asyncio.wait_for(awaitable, timeout)
        return response["result"]
    except (TimeoutError, OSError, qrc.QRCError, KeyError, TypeError) as err:
        raise DiscoveryError(
            "Unable to discover controls; retry when the Core is available"
        ) from err


def _named_items(items):
    if not isinstance(items, list) or any(
        not isinstance(item, dict) or not isinstance(item.get("Name"), str)
        for item in items
    ):
        raise DiscoveryError("Invalid discovery response")
    if len({item["Name"] for item in items}) != len(items):
        raise DiscoveryError("Ambiguous discovery response")
    return items


async def components(core, timeout=5):
    """Fetch current named components without a persistent cache."""
    return _named_items(await _request(core.component().get_components(), timeout))


async def controls(core, component, timeout=5):
    """Fetch controls and metadata only for the chosen component."""
    result = await _request(core.component().get_controls(component), timeout)
    if not isinstance(result, dict):
        raise DiscoveryError("Invalid component response")
    return _named_items(result.get("Controls"))


async def values(core, component, names, timeout=5):
    """Read current component values without repeating metadata discovery."""
    result = await _request(
        core.component().get(component, [{"Name": name} for name in names]), timeout
    )
    if not isinstance(result, dict):
        raise DiscoveryError("Invalid component response")
    return _named_items(result.get("Controls"))


async def named_control(core, name, timeout=5):
    """Validate an exact top-level Named Control name with Control.Get."""
    result = _named_items(await _request(core.control().get([name]), timeout))
    for control in result:
        if control["Name"] == name:
            return control
    raise MissingControlError("Named Control was not found")


def writable(control):
    """Return True, False, or None when direction metadata is absent."""
    direction = control.get("Direction")
    if direction is None:
        return None
    return str(direction).lower().replace(" ", "") in {
        "read/write",
        "write",
        "writeonly",
        "write-only",
    }


def compatible_platforms(control):
    """Match the value handling used by the existing entity platforms."""
    value = control.get("Value")
    kind = str(control.get("Type", "")).lower()
    boolean = kind == "boolean" or isinstance(value, bool)
    result = ["binary_sensor", "sensor"] if boolean else ["sensor"]
    if writable(control) is False:
        return result
    # Existing YAML switches also activate momentary Q-Sys trigger controls.
    if kind in {"boolean", "trigger"} or isinstance(value, bool):
        result.append("switch")
    elif kind in {"float", "integer", "number"} or (
        isinstance(value, (int, float)) and not isinstance(value, bool)
    ):
        result.append("number")
    if kind == "string" or isinstance(value, str):
        result.append("text")
    if (
        isinstance(control.get("Choices"), list)
        and control["Choices"]
        and all(isinstance(choice, str) for choice in control["Choices"])
    ):
        result.append("select")
    return result


def suggested_settings(platform, component, control):
    """Use explicit metadata for defaults without guessing units or ranges."""
    settings = {
        "component": component,
        "control": control["Name"],
        "name": control["Name"],
    }
    if platform == "number":
        for source, target in (
            ("ValueMin", "min"),
            ("ValueMax", "max"),
            ("Step", "step"),
        ):
            value = control.get(source)
            if (
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and math.isfinite(value)
            ):
                settings[target] = value
    if platform in {"number", "sensor"} and isinstance(control.get("Units"), str):
        settings["unit_of_measurement"] = control["Units"]
    if platform == "sensor":
        settings["attribute"] = "Value" if "Value" in control else "String"
    if platform == "select":
        settings["options"] = list(control.get("Choices", []))
    return settings


async def validate_mapping(core, mapping, timeout=5):
    """Inspect a mapping without ever issuing a Set command."""
    settings = mapping["settings"]
    component = settings.get("component")
    platform = mapping["platform"]
    if component:
        items = await components(core, timeout)
        match = next((item for item in items if item["Name"] == component), None)
        if match is None:
            return ["missing_component"]
        if platform == "media_player":
            return (
                []
                if match.get("Type") in MEDIA_COMPONENT_TYPES
                else ["unsupported_component_type"]
            )
        items = await controls(core, component, timeout)
        control = next(
            (item for item in items if item["Name"] == settings["control"]), None
        )
        if control is None:
            return ["missing_control"]
    else:
        try:
            control = await named_control(core, settings["control"], timeout)
        except MissingControlError:
            return ["missing_control"]
    if platform not in compatible_platforms(control):
        return [
            "read_only_mismatch"
            if writable(control) is False
            else "incompatible_control"
        ]
    return (
        ["writability_unverified"]
        if platform not in {"sensor", "binary_sensor"} and writable(control) is None
        else []
    )


class FlowCore:
    """Provide read-only discovery using a short-lived authenticated connection."""

    def __init__(self, connection):
        self.connection = connection

    def component(self):
        return qrc.ComponentAPI(self)

    def control(self):
        return qrc.ControlAPI(self)

    async def call(self, method, params=None):
        from contextlib import suppress
        from .const import CONF_HOST, CONF_PORT, CONF_USERNAME, CONF_PASSWORD

        core = qrc.Core(
            self.connection[CONF_HOST], self.connection.get(CONF_PORT, qrc.PORT)
        )
        runner = asyncio.create_task(core.run_until_stopped())
        try:
            async with asyncio.timeout(5):
                await core.wait_until_connected()
                response = await core.logon(
                    self.connection[CONF_USERNAME], self.connection[CONF_PASSWORD]
                )
                if not response.get("result", False):
                    raise DiscoveryError("Authentication failed")
                return await core.call(method, params)
        finally:
            runner.cancel()
            with suppress(asyncio.CancelledError):
                await runner
