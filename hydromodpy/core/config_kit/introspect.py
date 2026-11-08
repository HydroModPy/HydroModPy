"""Introspection helpers for HydroModPy Pydantic config fields.

Central location for logic that reads ``Annotated[...]`` metadata off
:class:`pydantic.fields.FieldInfo` - profile visibility, conditional
display, and any future metadata tags.

Kept separate from :mod:`hydromodpy.core.toml_io.generator` and
:mod:`hydromodpy.core.config_kit.dump` so TOML and JSON Schema
paths can share the same source of truth.
"""

from __future__ import annotations

import types
from collections.abc import Iterator, Mapping
from functools import cache
from pathlib import Path
from typing import Annotated, Any, TypeGuard, Union, get_args, get_origin

from pydantic import BaseModel, Field
from pydantic.fields import FieldInfo

from hydromodpy.core.config_kit.profile import Profile

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


def named_tables_of(
    model_cls: type[BaseModel], *, shipped_only: bool = True
) -> Mapping[str, type[BaseModel]]:
    """Return the tables *model_cls* holds under free names, by name, with their model.

    A model whose keys beyond its fields name a plugin, as ``[solver.modflow6]``
    names a flow solver, declares the class method ``named_tables``. *shipped_only*
    keeps the tables of the plugins this build ships, so a schema, a template or a
    page does not depend on what is installed beside it. Any other model holds none.
    """
    hook = getattr(model_cls, "named_tables", None)
    if hook is None:
        return {}
    return hook(shipped_only=shipped_only)


def held_tables_of(model: BaseModel) -> Mapping[str, BaseModel]:
    """Return the named tables an instance holds, by name; ``{}`` for a model without any."""
    hook = getattr(model, "held_tables", None)
    return {} if hook is None else hook()


def written_tables_of(model: BaseModel) -> Mapping[str, BaseModel]:
    """Return the named tables an instance holds that are not defaults taken in silence."""
    hook = getattr(model, "written_tables", None)
    return {} if hook is None else hook()


@cache
def _table_field(table: type[BaseModel]) -> FieldInfo:
    """Return a field that stands for a named table of model *table*, described by its docstring."""
    doc = (table.__doc__ or "").strip().split("\n\n", 1)[0]
    description = " ".join(line.strip() for line in doc.splitlines())
    return FieldInfo.from_annotated_attribute(
        Annotated[table, Profile.USER], Field(default_factory=table, description=description)
    )


def fields_and_tables(
    model_cls: type[BaseModel], *, shipped_only: bool = True
) -> dict[str, FieldInfo]:
    """Return the fields of *model_cls*, then one field per named table it holds.

    This is the one reader of a model's keys for the generic walkers: the dotted
    paths of ``--set``, the template, the schema, the parameter pages. A named
    table reads as a field of its model, so ``solver.modflow6.runtime`` resolves
    like any nested section.
    """
    found = dict(model_cls.model_fields)
    for name, table in named_tables_of(model_cls, shipped_only=shipped_only).items():
        found.setdefault(name, _table_field(table))
    return found


def child_of(model: BaseModel, name: str) -> Any:
    """Return the field *name* of an instance, or the named table it holds under *name*.

    Raises
    ------
    AttributeError
        When *model* has neither.
    """
    if name in type(model).model_fields:
        return getattr(model, name)
    held = held_tables_of(model)
    if name in held:
        return held[name]
    raise AttributeError(f"{type(model).__name__} has no field or table {name!r}")


def iter_fields_by_profile(
    model_cls: type[BaseModel],
    threshold: Profile,
) -> Iterator[tuple[str, FieldInfo, Profile]]:
    """Yield ``(name, field_info, level)`` for fields visible at *threshold*.

    A field is visible when its declared :class:`Profile` is ``<= threshold``
    (USER < DEV < EXPERT). Single source of truth used by the TOML generator,
    the TOML serializer, and the JSON Schema exporter. The named tables the
    model holds come after its fields (:func:`fields_and_tables`).
    """
    for name, info in fields_and_tables(model_cls).items():
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


def iter_basemodels(annotation: Any) -> list[type[BaseModel]]:
    """Return every :class:`BaseModel` subclass reachable through *annotation*.

    Enumerates every variant of a union, so a caller can resolve a path against
    each candidate and pick the one that declares the next segment, or refuse an
    ambiguous one. :func:`_resolve_field_basemodel` answers a different
    question -- "the single model to recurse into" -- and takes the first match.
    """
    from pydantic import BaseModel as _BaseModel

    found: list[type[BaseModel]] = []
    seen: set[type[BaseModel]] = set()

    def _walk(node: Any) -> None:
        if isinstance(node, type) and issubclass(node, _BaseModel):
            if node not in seen:
                seen.add(node)
                found.append(node)
            return
        for arg in getattr(node, "__args__", ()) or ():
            _walk(arg)

    _walk(annotation)
    return found


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
    for name, info in fields_and_tables(model_cls, shipped_only=False).items():
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


LIST_ITEM_MARK = "[]"
"""Suffix of a path part that is a list: the path continues inside each item."""

TABLE_KEY_MARK = "*"
"""Path part standing for any key of a ``dict[str, Model]`` table."""


def is_site_scoped(field_info: Any) -> bool:
    """Return whether *field_info* carries ``site_scoped=True`` in its metadata."""
    extra = getattr(field_info, "json_schema_extra", None)
    return isinstance(extra, dict) and extra.get("site_scoped") is True


def is_union_origin(origin: object) -> bool:
    """Return True when *origin* is the origin of a ``Union[...]`` or ``X | Y`` annotation."""
    return origin is Union or origin is types.UnionType


def is_implicit_relative_path_default(value: Any, field_info: Any) -> bool:
    """Return True when *value* is the relative ``Path`` default of the field.

    Such a value is the project layout speaking, so a template and a written
    config leave it out. A string that names the same path counts too.
    """
    default = field_info.default
    if not isinstance(default, Path) or default.is_absolute():
        return False
    if isinstance(value, Path):
        return value == default
    if isinstance(value, str):
        return Path(value) == default
    return False


def is_model(annotation: object) -> TypeGuard[type[BaseModel]]:
    """Return True when *annotation* is a Pydantic model class."""
    return isinstance(annotation, type) and issubclass(annotation, BaseModel)


def unwrap_members(annotation: Any) -> list[Any]:
    """Return the members of an annotation, ``Annotated`` and ``None`` removed."""
    origin = get_origin(annotation)
    if origin is Annotated:
        return unwrap_members(get_args(annotation)[0])
    if is_union_origin(origin):
        out: list[Any] = []
        for arg in get_args(annotation):
            out.extend(unwrap_members(arg))
        return out
    if annotation is type(None):
        return []
    return [annotation]


def site_scoped_paths(model: type[BaseModel]) -> tuple[str, ...]:
    """Return the dotted paths of every field marked ``site_scoped`` under *model*.

    The walk follows nested models, every variant of a union, list items and
    ``dict[str, Model]`` values. A part that is a list ends in ``[]``
    (``data.hydrometry.sources[].station_ids``) and a table key is written
    ``*`` (``calibration.outputs.*.observes``): these are patterns over a
    resolved document, not key paths a ``--set`` could assign. Paths are
    sorted and unique.
    """
    found: set[str] = set()

    def _walk(cls: type[BaseModel], prefix: tuple[str, ...], stack: tuple[type, ...]) -> None:
        if cls in stack:
            return
        for name, info in fields_and_tables(cls).items():
            here = (*prefix, name)
            if is_site_scoped(info):
                found.add(".".join(here))
            _descend(info.annotation, here, (*stack, cls))

    def _descend(annotation: Any, here: tuple[str, ...], stack: tuple[type, ...]) -> None:
        for member in unwrap_members(annotation):
            if is_model(member):
                _walk(member, here, stack)
                continue
            origin = get_origin(member)
            args = get_args(member)
            if origin in {list, tuple, set, frozenset} and args:
                marked = (*here[:-1], here[-1] + LIST_ITEM_MARK)
                for arg in args:
                    if arg is not Ellipsis:
                        _descend(arg, marked, stack)
            elif origin is dict and len(args) == 2:
                _descend(args[1], (*here, TABLE_KEY_MARK), stack)

    _walk(model, (), ())
    return tuple(sorted(found))


__all__ = [
    "DEFAULT_FIELD_PROFILE",
    "LIST_ITEM_MARK",
    "TABLE_KEY_MARK",
    "child_of",
    "collect_profile_violations",
    "extract_profile",
    "fields_and_tables",
    "held_tables_of",
    "iter_basemodels",
    "is_site_scoped",
    "iter_fields_by_profile",
    "named_tables_of",
    "read_profile_from_schema",
    "resolve_profile",
    "site_scoped_paths",
    "written_tables_of",
]
