"""Read-only gain validation and reversible listening-range conversion."""

from dataclasses import dataclass
import math

import voluptuous as vol


def volume_defaults(settings):
    """Keep omitted YAML settings legacy; explicit dB bounds opt in."""
    if not isinstance(settings, dict):
        raise vol.Invalid("Entity settings must be a mapping")
    settings = dict(settings)
    settings.setdefault(
        "volume_mode", "db" if {"min_db", "max_db"} & settings.keys() else "legacy"
    )
    return settings


def validate_volume_settings(settings):
    """Validate finite, increasing bounds in YAML and UI mappings alike."""
    if not all(math.isfinite(settings[key]) for key in ("min_db", "max_db")):
        raise vol.Invalid("min_db and max_db must be finite")
    if settings["min_db"] >= settings["max_db"]:
        raise vol.Invalid("min_db must be less than max_db")
    return settings


def is_db_gain(control):
    """Recognize explicit Q-SYS dB metadata, including standard QRC strings."""
    return str(control.get("Units", "")).lower() == "db" or any(
        str(control.get(key, "")).lower().endswith("db")
        for key in ("StringMin", "StringMax", "String")
    )


@dataclass(frozen=True)
class GainRange:
    """One control's listening range and separately discovered silent value."""

    min_db: float
    max_db: float
    control_min: float

    @classmethod
    def from_control(cls, settings, control):
        """Verify bounds without probing or changing the control's gain."""
        limits = [control.get("ValueMin"), control.get("ValueMax")]
        if any(
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(value)
            for value in limits
        ):
            raise vol.Invalid("Q-SYS gain limits are unavailable")
        minimum, maximum = limits
        low, high = settings["min_db"], settings["max_db"]
        if not minimum <= low < high <= maximum:
            raise vol.Invalid(
                f"Listening range {low}..{high} dB must fit Q-SYS gain limits "
                f"{minimum}..{maximum} dB"
            )
        return cls(low, high, minimum)

    def to_db(self, level):
        """Map normalized volume to dB; zero uses the available minimum."""
        level = max(0.0, min(1.0, level))
        return (
            self.control_min
            if level == 0
            else self.min_db + level * (self.max_db - self.min_db)
        )

    def to_level(self, value):
        """Clamp only the displayed volume, never the underlying gain."""
        return max(0.0, min(1.0, (value - self.min_db) / (self.max_db - self.min_db)))


def media_gain_names(component_type):
    """Return all channel gains controlled by a supported media player."""
    return (
        ("channel.1.gain", "channel.2.gain")
        if component_type == "URL_receiver"
        else ("gain",)
    )
