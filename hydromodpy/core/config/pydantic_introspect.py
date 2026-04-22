"""Introspection helpers for HydroModPy Pydantic config fields.

Central location for logic that reads ``Annotated[...]`` metadata off
:class:`pydantic.fields.FieldInfo` — profile visibility, conditional
display, and any future metadata tags.

Kept separate from :mod:`hydromodpy.core.config.generate_toml` and
:mod:`hydromodpy.core.config.toml_io` so TOML, Streamlit, and JSON Schema
paths can share the same source of truth.
"""

from __future__ import annotations

from typing import Any

from hydromodpy.core.config.param_level import ParamLevel
from hydromodpy.core.config.profile import Profile

#: Fields without an explicit ``Profile`` / ``ParamLevel`` tag default to
#: :attr:`Profile.USER` so they always appear in generated templates.
DEFAULT_FIELD_PROFILE: Profile = Profile.USER


def extract_profile(field_info: Any) -> Profile:
    """Return the :class:`Profile` declared on *field_info*.

    Accepts both the new ``Profile`` enum tag and the legacy
    :class:`ParamLevel` dataclass tag in ``Annotated[...]`` metadata.
    Falls back to :data:`DEFAULT_FIELD_PROFILE` when no tag is found.
    """
    for meta in getattr(field_info, "metadata", ()):
        if isinstance(meta, Profile):
            return meta
        if isinstance(meta, ParamLevel):
            return meta.as_profile()
    return DEFAULT_FIELD_PROFILE


def resolve_profile(profile: Profile | str) -> Profile:
    """Coerce a profile name (``"user"``/``"dev"``/``"expert"``) or enum to :class:`Profile`.

    Raises :class:`ValueError` when *profile* is an unknown string.
    """
    if isinstance(profile, Profile):
        return profile
    try:
        return Profile[profile.upper()]
    except (KeyError, AttributeError) as exc:
        allowed = ", ".join(p.name.lower() for p in Profile)
        raise ValueError(f"Unknown profile {profile!r}. Allowed values: {allowed}.") from exc


__all__ = ["extract_profile", "resolve_profile", "DEFAULT_FIELD_PROFILE"]
