"""Profile selection for testbed-backed campaign launchers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from hydromodpy.analysis.config_helpers import optional_text, require_mapping

GENERIC_TESTBED_PROFILE = "generic"
REGIONAL_LAB_PROFILE = "regional_lab"
SUPPORTED_TESTBED_PROFILES = {
    GENERIC_TESTBED_PROFILE,
    REGIONAL_LAB_PROFILE,
}


def resolve_testbed_profile(raw_toml: Mapping[str, Any]) -> str:
    """Return the normalized testbed profile declared by a raw TOML payload."""
    if "testbed" not in raw_toml:
        return GENERIC_TESTBED_PROFILE
    section = require_mapping(raw_toml.get("testbed"), label="testbed")
    profile = (optional_text(section.get("profile")) or GENERIC_TESTBED_PROFILE).lower()
    if profile not in SUPPORTED_TESTBED_PROFILES:
        raise ValueError(
            f"Unsupported testbed.profile '{profile}'. "
            f"Supported values: {', '.join(sorted(SUPPORTED_TESTBED_PROFILES))}."
        )
    return profile


__all__ = [
    "GENERIC_TESTBED_PROFILE",
    "REGIONAL_LAB_PROFILE",
    "SUPPORTED_TESTBED_PROFILES",
    "resolve_testbed_profile",
]
