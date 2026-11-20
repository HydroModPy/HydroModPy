"""Which Pydantic model a field holds, and which member of a union.

The section walker reads annotations through these: a nested model, a list of
models, a mapping of models, the union member a value pins with its
discriminator, and the discriminator tags a dump leaves out.
"""

from __future__ import annotations

import typing
from collections.abc import Mapping as _abc_Mapping
from enum import Enum
from typing import Any, get_args, get_origin

from pydantic import BaseModel
from pydantic.fields import FieldInfo

from hydromodpy.core.config_kit.introspect import held_tables_of, is_union_origin


def is_mapping_field(field_info: FieldInfo) -> bool:
    """True when the field annotation is a mapping (``dict``/``Mapping``).

    A mapping field must never be emitted as an inline ``name = {}`` in a
    template: an inline table cannot be extended by later
    ``[section.name.<id>]`` sub-tables (e.g. the dynamic ``[flow.param.*]``
    blocks), which produces invalid TOML.
    """
    annotation = field_info.annotation
    candidates = (
        list(get_args(annotation)) if is_union_origin(get_origin(annotation)) else [annotation]
    )
    for cand in candidates:
        origin = get_origin(cand)
        if origin is dict:
            return True
        if isinstance(origin, type) and issubclass(origin, _abc_Mapping):
            return True
    return False


def _unwrap_optional(annotation: Any) -> Any:
    """Return the single non-None member of an optional annotation."""
    if not is_union_origin(get_origin(annotation)):
        return annotation
    members = [arg for arg in get_args(annotation) if arg is not type(None)]
    return members[0] if len(members) == 1 else annotation


def _model_members(annotation: Any) -> list[type[BaseModel]]:
    """Return the BaseModel members of an annotation, union or not."""
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return [annotation]
    members = [a for a in get_args(annotation) if isinstance(a, type) and issubclass(a, BaseModel)]
    if members:
        return members
    for arg in get_args(annotation):
        members.extend(
            sub for sub in get_args(arg) if isinstance(sub, type) and issubclass(sub, BaseModel)
        )
    return members


def variant_tag_field(model_cls: type[BaseModel]) -> str | None:
    """Return the field a model pins itself with, if it has one."""
    for name, info in model_cls.model_fields.items():
        if get_origin(info.annotation) is typing.Literal and len(get_args(info.annotation)) == 1:
            return name
    return None


def restore_variant_tags(model: BaseModel, values: Any) -> None:
    """Put back, in *values*, every tag the dump dropped as a default.

    Each member of a discriminated union defaults its own discriminator to its
    own tag, so ``exclude_defaults`` drops it from every member alike. A table
    that reaches the reader without its tag is not merely undecorated: both the
    renderer and the reload fall back to the member the field defaults to, and a
    ``flat_substratum`` comes back as a ``constant_thickness`` without a word. A
    tag is the one key a minimal document cannot leave out.
    """
    if not isinstance(values, dict):
        return
    tag = variant_tag_field(type(model))
    if tag is not None and tag not in values:
        held = getattr(model, tag, None)
        if held is not None:
            values[tag] = held.value if isinstance(held, Enum) else held
    for name in type(model).model_fields:
        if name not in values:
            continue
        _restore_tags_in_value(getattr(model, name, None), values[name])
    for name, table in held_tables_of(model).items():
        if name in values:
            restore_variant_tags(table, values[name])


def _restore_tags_in_value(held: Any, dumped: Any) -> None:
    """Walk one field's value and its dump side by side."""
    if isinstance(held, BaseModel):
        restore_variant_tags(held, dumped)
    elif isinstance(held, (list, tuple)) and isinstance(dumped, list):
        for item, item_dump in zip(held, dumped, strict=False):
            _restore_tags_in_value(item, item_dump)
    elif isinstance(held, dict) and isinstance(dumped, dict):
        for key, item in held.items():
            if key in dumped:
                _restore_tags_in_value(item, dumped[key])


def variant_for_values(
    field_info: FieldInfo,
    fallback: type[BaseModel],
    values: Any,
) -> type[BaseModel]:
    """Return the union member *values* pins with its discriminator.

    A field holding a discriminated union renders the member the caller
    actually holds, never the member the field falls back to. The members
    declare different keys, so a table built from the wrong one drops what the
    value carries and writes what the value forbids: ``depth_model`` set to
    ``flat_substratum`` lost its ``substratum_elevation`` and gained the
    ``thickness`` of the other variant, which reload then refused.
    """
    if not isinstance(values, dict):
        return fallback
    discriminator = field_info.discriminator
    if discriminator is None:
        return fallback
    tag = values.get(discriminator)
    if tag is None:
        return fallback
    members = _model_members(field_info.annotation)
    for member in members:
        info = member.model_fields.get(discriminator)
        if info is None:
            continue
        if get_origin(info.annotation) is typing.Literal and tag in get_args(info.annotation):
            return member
    return fallback


def resolve_mapping_basemodel_types(field_info: FieldInfo) -> list[type[BaseModel]]:
    """Return the model variants a ``dict[str, Model]`` field holds.

    Empty for a free-form mapping such as ``dict[str, Any]``, which has no
    shape to show.
    """
    annotation = _unwrap_optional(field_info.annotation)
    origin = get_origin(annotation)
    if origin is not dict and not (isinstance(origin, type) and issubclass(origin, _abc_Mapping)):
        return []
    args = get_args(annotation)
    return _model_members(args[1]) if len(args) == 2 else []


def resolve_list_basemodel_type(field_info: FieldInfo) -> type[BaseModel] | None:
    """If field is ``list[SomeBaseModel]``, return the item class, else None.

    Handles ``list[Annotated[Union[A, B], Field(discriminator=...)]]`` by
    returning a representative concrete BaseModel from the union (preferring
    the default_factory's runtime type when one item is set).
    """
    annotation = _unwrap_optional(field_info.annotation)
    if get_origin(annotation) is not list:
        return None
    args = get_args(annotation)
    if not args:
        return None
    item = args[0]
    if isinstance(item, type) and issubclass(item, BaseModel):
        return item

    candidates = _model_members(item)
    if not candidates:
        return None

    if field_info.default_factory is not None:
        try:
            default_value = field_info.default_factory()
        except Exception:
            default_value = None
        if isinstance(default_value, list) and default_value:
            head = default_value[0]
            if isinstance(head, BaseModel):
                return type(head)
    return candidates[0]


def resolve_basemodel_type(field_info: FieldInfo) -> type[BaseModel] | None:
    """Return the concrete BaseModel subclass if the field holds one, else None.

    Container fields (``list[M]``, ``dict[str, M]``) are **not** considered
    nested model fields -- only direct ``M`` or ``Optional[M]`` / ``Union[M, N]``.
    """
    annotation = field_info.annotation

    # Direct BaseModel subclass
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return annotation

    origin = get_origin(annotation)
    if origin is None:
        return None

    # Skip container types (list, dict, set, tuple, ...)
    if isinstance(origin, type) and issubclass(origin, (list, dict, set, tuple, frozenset)):
        return None

    # Handle Union types (typing.Union, types.UnionType)
    args = get_args(annotation)
    if not args:
        return None

    non_none = [a for a in args if a is not type(None)]
    base_models = [a for a in non_none if isinstance(a, type) and issubclass(a, BaseModel)]

    if not base_models:
        return None

    # Prefer the default_factory's concrete type for discriminated unions
    if field_info.default_factory is not None:
        try:
            instance = field_info.default_factory()
            if isinstance(instance, BaseModel):
                return type(instance)
        except Exception:
            pass
    if isinstance(field_info.default, BaseModel):
        return type(field_info.default)
    return base_models[0]
