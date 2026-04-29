"""Round-trip TOML helpers powered by :mod:`tomlkit`.

The architecture spec (``architecture_cible/02_config_pydantic.md`` §7)
requires that a :class:`HydroModelBase` instance be serialisable to a
commented TOML document, with fields filtered by the requested
:class:`~hydromodpy.master_config.profile.Profile` so that
``hmp config --profile user`` emits a small user-friendly template and
``--profile expert`` emits the full document.

The helpers here only handle **serialisation**; loading is covered by
``toml_loader.py`` and :meth:`HydroModPyConfig.from_toml`. The goal is
that for any fully resolved config instance::

    from hydromodpy.master_config.toml_io import dump_toml_with_comments

    dump_toml_with_comments(cfg, "out.toml", profile="expert")

produces a TOML file whose re-load (``HydroModPyConfig.from_toml``)
yields a config equal to the original.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import tomlkit
from pydantic import BaseModel
from tomlkit.items import Item

from hydromodpy.master_config.profile import Profile
from hydromodpy.master_config.pydantic_introspect import (
    extract_profile as _field_level,
)
from hydromodpy.master_config.pydantic_introspect import (
    resolve_profile as _resolve_profile,
)

ProfileName = str


def _coerce_value(value: Any) -> Any:
    """Convert Python values into something :mod:`tomlkit` can serialise.

    Supported transformations:

    * :class:`pathlib.Path` → string (POSIX form for portability)
    * ``pint.Quantity`` → ``"<magnitude> <units>"``
    * tuples → lists
    * nested mappings → ``tomlkit.table`` is handled by the caller; this
      helper only deals with scalar leaves.
    """
    if isinstance(value, Path):
        return str(value)
    # pint Quantities arrive as typing.Any so rely on duck typing.
    if hasattr(value, "magnitude") and hasattr(value, "units"):
        return f"{value.magnitude} {value.units:~}"
    if isinstance(value, tuple):
        return [_coerce_value(v) for v in value]
    if isinstance(value, list):
        return [_coerce_value(v) for v in value]
    return value


def _iter_serialisable_fields(
    model: BaseModel,
    *,
    profile_threshold: Profile,
) -> Iterable[tuple[str, Any, Any]]:
    """Yield ``(field_name, field_info, value)`` triples for *model*.

    Fields whose :class:`Profile` exceeds *profile_threshold* are
    skipped. The yielded value is the live attribute on *model*
    (already validated).
    """
    for field_name, info in type(model).model_fields.items():
        if _field_level(info) > profile_threshold:
            continue
        yield field_name, info, getattr(model, field_name)


_SENTINEL_MISSING = object()


def _render_container_value(value: Any, *, profile_threshold: Profile) -> Item | Any:
    """Render *value* into a :mod:`tomlkit`-friendly representation.

    Returns :data:`_SENTINEL_MISSING` when the value has no TOML
    representation (``None``) so callers can skip the field entirely.
    """
    if value is None:
        return _SENTINEL_MISSING
    if isinstance(value, BaseModel):
        return _render_model_table(value, profile_threshold=profile_threshold)
    if isinstance(value, Mapping):
        table = tomlkit.table()
        for key, sub in value.items():
            rendered = _render_container_value(sub, profile_threshold=profile_threshold)
            if rendered is _SENTINEL_MISSING:
                continue
            table[str(key)] = rendered
        return table
    if isinstance(value, (list, tuple)):
        array = tomlkit.array()
        for sub in value:
            rendered = _render_container_value(sub, profile_threshold=profile_threshold)
            if rendered is _SENTINEL_MISSING:
                continue
            array.append(rendered)
        return array
    return _coerce_value(value)


def _render_model_table(model: BaseModel, *, profile_threshold: Profile) -> Item:
    """Render a Pydantic model as a :func:`tomlkit.table` honouring *profile_threshold*."""
    table = tomlkit.table()
    for field_name, info, value in _iter_serialisable_fields(
        model, profile_threshold=profile_threshold
    ):
        rendered = _render_container_value(value, profile_threshold=profile_threshold)
        if rendered is _SENTINEL_MISSING:
            continue
        table[field_name] = rendered
        description = getattr(info, "description", None)
        if description:
            try:
                table[field_name].comment(description)
            except AttributeError:
                # Primitive leaves (bare str/int/…) don't carry comments in
                # tomlkit; leave them bare rather than forcing a wrap.
                pass
    return table


def dump_toml_with_comments(
    model: BaseModel,
    path: str | Path,
    *,
    profile: ProfileName = "user",
) -> Path:
    """Serialise *model* to a TOML document at *path*.

    Parameters
    ----------
    model
        Any :class:`~hydromodpy.master_config.base.HydroModelBase` instance.
    path
        Destination file path. The parent directory must already exist.
    profile
        One of ``"user"``, ``"dev"``, ``"expert"``. Fields whose
        :class:`Profile` exceeds the requested profile are omitted.

    Returns
    -------
    pathlib.Path
        The resolved destination path.
    """
    threshold = _resolve_profile(profile)
    doc = tomlkit.document()
    doc.add(tomlkit.comment("Generated by hydromodpy.master_config.toml_io"))
    doc.add(tomlkit.comment(f"profile = {profile!r}"))
    doc.add(tomlkit.nl())
    for field_name, _info, value in _iter_serialisable_fields(model, profile_threshold=threshold):
        rendered = _render_container_value(value, profile_threshold=threshold)
        if rendered is _SENTINEL_MISSING:
            continue
        doc[field_name] = rendered
    destination = Path(path)
    destination.write_text(tomlkit.dumps(doc), encoding="utf-8")
    return destination


__all__ = ["dump_toml_with_comments"]
