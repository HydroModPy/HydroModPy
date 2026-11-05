"""TOML writing helpers.

``dumps`` and ``dump`` render a plain mapping with tomli-w.
``dump_toml_with_comments`` serializes a :class:`HydroModelBase` instance to a
commented TOML document (tomlkit) filtered by the requested :class:`Profile`:
``--profile user`` emits a user-friendly document and ``--profile expert`` the
full one. Loading is covered by ``loader.py`` and
:meth:`HydroModPyConfig.from_toml`; the re-load of a dumped config yields a
config equal to the original.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any, cast

import tomli_w
import tomlkit
from pydantic import BaseModel
from tomlkit.items import Item, Table

from hydromodpy.core.config_kit.introspect import (
    iter_fields_by_profile,
)
from hydromodpy.core.config_kit.introspect import (
    resolve_profile as _resolve_profile,
)
from hydromodpy.core.config_kit.profile import Profile, ProfileName
from hydromodpy.core.config_kit.written import written_fields


def dumps(payload: Mapping[str, Any]) -> str:
    """Return *payload* rendered as TOML text."""
    return cast(str, tomli_w.dumps(payload))


def dump(payload: Mapping[str, Any], fp: Any) -> None:
    """Write *payload* to a file object."""
    tomli_w.dump(payload, fp)


def _coerce_value(value: Any) -> Any:
    """Convert Python values into something :mod:`tomlkit` can serialize.

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
    written_only: bool = False,
) -> Iterable[tuple[str, Any, Any]]:
    """Yield ``(field_name, field_info, value)`` triples for *model*.

    Fields whose :class:`Profile` exceeds *profile_threshold* are
    skipped, and so are the fields *model* was not given when
    *written_only* is set. The yielded value is the live attribute on
    *model* (already validated).
    """
    written = set(written_fields(model)) if written_only else None
    for field_name, info, _level in iter_fields_by_profile(type(model), profile_threshold):
        if written is not None and field_name not in written:
            continue
        extra = getattr(info, "json_schema_extra", None)
        if isinstance(extra, dict) and extra.get("toml_exclude") is True:
            continue
        yield field_name, info, getattr(model, field_name)


def _is_implicit_relative_path_default(value: Any, field_info: Any) -> bool:
    default = getattr(field_info, "default", None)
    return (
        isinstance(value, Path)
        and isinstance(default, Path)
        and value == default
        and not value.is_absolute()
    )


def _inline_comment(description: str | None) -> str:
    for line in (description or "").splitlines():
        text = line.strip()
        if text:
            return text
    return ""


_SENTINEL_MISSING = object()


def _render_container_value(
    value: Any, *, profile_threshold: Profile, written_only: bool = False
) -> Item | Any:
    """Render *value* into a :mod:`tomlkit`-friendly representation.

    Returns :data:`_SENTINEL_MISSING` when the value has no TOML
    representation (``None``) so callers can skip the field entirely.
    """
    if value is None:
        return _SENTINEL_MISSING
    if isinstance(value, BaseModel):
        return _render_model_table(
            value, profile_threshold=profile_threshold, written_only=written_only
        )
    if isinstance(value, Mapping):
        table = tomlkit.table()
        for key, sub in value.items():
            rendered = _render_container_value(
                sub, profile_threshold=profile_threshold, written_only=written_only
            )
            if rendered is _SENTINEL_MISSING:
                continue
            table[str(key)] = rendered
        return table
    if isinstance(value, (list, tuple)):
        rendered_items: list[Item | Any] = []
        has_table = False
        for sub in value:
            rendered = _render_container_value(
                sub, profile_threshold=profile_threshold, written_only=written_only
            )
            if rendered is _SENTINEL_MISSING:
                continue
            rendered_items.append(rendered)
            has_table = has_table or isinstance(rendered, Table)
        if has_table:
            aot = tomlkit.aot()
            for rendered in rendered_items:
                if not isinstance(rendered, Table):
                    msg = "Mixed scalar and table lists cannot be serialized to TOML."
                    raise TypeError(msg)
                aot.append(rendered)
            return aot
        array = tomlkit.array()
        for rendered in rendered_items:
            array.append(rendered)
        return array
    return _coerce_value(value)


def _render_model_table(
    model: BaseModel, *, profile_threshold: Profile, written_only: bool = False
) -> Item:
    """Render a Pydantic model as a :func:`tomlkit.table` honoring *profile_threshold*."""
    table = tomlkit.table()
    for field_name, info, value in _iter_serialisable_fields(
        model, profile_threshold=profile_threshold, written_only=written_only
    ):
        if _is_implicit_relative_path_default(value, info):
            continue
        rendered = _render_container_value(
            value, profile_threshold=profile_threshold, written_only=written_only
        )
        if rendered is _SENTINEL_MISSING:
            continue
        table[field_name] = rendered
        description = _inline_comment(getattr(info, "description", None))
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
    written_only: bool = False,
) -> Path:
    """Serialize *model* to a TOML document at *path*.

    Parameters
    ----------
    model
        Any :class:`~hydromodpy.core.config_kit.base.HydroModelBase` instance.
    path
        Destination file path. The parent directory must already exist.
    profile
        One of ``"user"``, ``"dev"``, ``"expert"``. Fields whose
        :class:`Profile` exceeds the requested profile are omitted.
    written_only
        Keep only the fields the model was given
        (:func:`~hydromodpy.core.config_kit.written.written_fields`), so the
        document validates back into a model with the same fields set.

    Returns
    -------
    pathlib.Path
        The resolved destination path.
    """
    threshold = _resolve_profile(profile)
    doc = tomlkit.document()
    doc.add(tomlkit.comment("Generated by hydromodpy.core.toml_io.writer"))
    doc.add(tomlkit.comment(f"profile = {profile!r}"))
    doc.add(tomlkit.nl())
    for field_name, _info, value in _iter_serialisable_fields(
        model, profile_threshold=threshold, written_only=written_only
    ):
        rendered = _render_container_value(
            value, profile_threshold=threshold, written_only=written_only
        )
        if rendered is _SENTINEL_MISSING:
            continue
        doc[field_name] = rendered
    destination = Path(path)
    destination.write_text(tomlkit.dumps(doc), encoding="utf-8")
    return destination


__all__ = ["dump", "dump_toml_with_comments", "dumps"]
