"""Introspection helpers for HydroModPy Pydantic config fields.

Central location for logic that reads ``Annotated[...]`` metadata off
:class:`pydantic.fields.FieldInfo` - profile visibility, conditional
display, and any future metadata tags.

Kept separate from :mod:`hydromodpy.core.toml_io.generator` and
:mod:`hydromodpy.core.toml_io.io` so TOML, Streamlit, and JSON Schema
paths can share the same source of truth.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING, Any

from hydromodpy.core.config_kit.profile import Profile

if TYPE_CHECKING:
    from pydantic import BaseModel
    from pydantic.fields import FieldInfo

#: Fields without an explicit ``Profile`` tag default to :attr:`Profile.USER`
#: so they always appear in generated templates.
DEFAULT_FIELD_PROFILE: Profile = Profile.USER


def extract_profile(field_info: Any) -> Profile:
    """Return the :class:`Profile` declared on *field_info*.

    Falls back to :data:`DEFAULT_FIELD_PROFILE` when no tag is found.
    """
    for meta in getattr(field_info, "metadata", ()):
        if isinstance(meta, Profile):
            return meta
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


def iter_fields_by_profile(
    model_cls: type[BaseModel],
    threshold: Profile,
) -> Iterator[tuple[str, FieldInfo, Profile]]:
    """Yield ``(name, field_info, level)`` for fields visible at *threshold*.

    A field is visible when its declared :class:`Profile` is ``<= threshold``
    (USER < DEV < EXPERT). Single source of truth used by the TOML generator,
    the TOML serializer, and the JSON Schema exporter.
    """
    for name, info in model_cls.model_fields.items():
        level = extract_profile(info)
        if level > threshold:
            continue
        yield name, info, level


def read_profile_from_schema(field_schema: dict[str, Any]) -> Profile | None:
    """Return the :class:`Profile` declared via ``x-hmp-profile`` on a JSON schema node."""
    level_name = field_schema.get("x-hmp-profile")
    if not isinstance(level_name, str):
        return None
    try:
        return Profile[level_name.upper()]
    except KeyError:
        return None


def _resolve_field_basemodel(field_info: Any) -> type[BaseModel] | None:
    """Return the :class:`BaseModel` subclass referenced by *field_info*, when applicable."""
    from typing import Union, get_args, get_origin

    from pydantic import BaseModel as _BaseModel

    annotation = getattr(field_info, "annotation", None)
    candidates: list[Any] = [annotation]
    args = get_args(annotation)
    if get_origin(annotation) is Union and args:
        candidates.extend(args)
    elif args:
        candidates.extend(args)
    for cand in candidates:
        if isinstance(cand, type) and issubclass(cand, _BaseModel):
            return cand
    return None


def collect_profile_violations(
    model_cls: type[BaseModel],
    payload: Any,
    threshold: Profile,
    *,
    _path: tuple[str, ...] = (),
) -> list[tuple[tuple[str, ...], Profile]]:
    """Return ``(path, level)`` for every payload key whose Profile exceeds *threshold*.

    Walks raw mapping payloads (typically a TOML dict pre-validation) and reports
    any user-supplied key whose declared :class:`Profile` is stricter than the
    declared *threshold*. Used to surface "user TOML mentions an expert field"
    situations as warnings without blocking validation.
    """
    if not isinstance(payload, dict):
        return []
    violations: list[tuple[tuple[str, ...], Profile]] = []
    for name, info in model_cls.model_fields.items():
        if name not in payload:
            continue
        level = extract_profile(info)
        sub_path = (*_path, name)
        if level > threshold:
            violations.append((sub_path, level))
            continue
        nested_cls = _resolve_field_basemodel(info)
        if nested_cls is None:
            continue
        value = payload[name]
        if isinstance(value, dict):
            violations.extend(
                collect_profile_violations(nested_cls, value, threshold, _path=sub_path)
            )
        elif isinstance(value, list):
            for idx, item in enumerate(value):
                violations.extend(
                    collect_profile_violations(
                        nested_cls,
                        item,
                        threshold,
                        _path=(*sub_path, f"[{idx}]"),
                    )
                )
    return violations


__all__ = [
    "DEFAULT_FIELD_PROFILE",
    "collect_profile_violations",
    "extract_profile",
    "iter_fields_by_profile",
    "read_profile_from_schema",
    "resolve_profile",
]
