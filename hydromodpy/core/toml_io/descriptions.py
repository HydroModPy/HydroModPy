"""Description lookup for commented TOML mapping exports."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, get_args, get_origin

from pydantic import BaseModel

from hydromodpy.core.config_kit.registry import root_scalar_fields, root_sections


def clean_description(value: object) -> str | None:
    text = "" if value is None else str(value).strip()
    if not text:
        return None
    return " ".join(text.split())


def model_field_description(model_cls: type[BaseModel], field_name: str) -> str | None:
    field_info = model_cls.model_fields.get(field_name)
    if field_info is None:
        return None
    return clean_description(field_info.description)


def _resolve_model_type(annotation: Any) -> type[BaseModel] | None:
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return annotation

    origin = get_origin(annotation)
    if origin is None:
        return None

    for arg in get_args(annotation):
        nested = _resolve_model_type(arg)
        if nested is not None:
            return nested
    return None


def _resolve_list_model_type(annotation: Any) -> type[BaseModel] | None:
    origin = get_origin(annotation)
    if origin not in {list, tuple}:
        return None
    for arg in get_args(annotation):
        nested = _resolve_model_type(arg)
        if nested is not None:
            return nested
    return None


def _iter_union_model_types(annotation: Any) -> list[type[BaseModel]]:
    """Return every BaseModel subclass referenced by a (possibly nested) Union."""
    seen: list[type[BaseModel]] = []

    def _visit(value: Any) -> None:
        if isinstance(value, type) and issubclass(value, BaseModel):
            if value not in seen:
                seen.append(value)
            return
        for arg in get_args(value):
            _visit(arg)

    _visit(annotation)
    return seen


def _union_variant_field_description(
    model_cls: type[BaseModel],
    field_name: str,
) -> str | None:
    """Resolve a description from sibling discriminated-union variants."""
    for info in model_cls.model_fields.values():
        for variant in _iter_union_model_types(info.annotation):
            variant_info = variant.model_fields.get(field_name)
            if variant_info is not None and variant_info.description:
                return clean_description(variant_info.description)
    return None


def _union_variant_description(annotation: Any, parts: Sequence[str]) -> str | None:
    """Resolve a nested description from every model variant in one union."""
    for variant in _iter_union_model_types(annotation):
        description = model_description_for_path(variant, parts)
        if description:
            return description
    return None


def model_description_for_path(
    model_cls: type[BaseModel],
    parts: Sequence[str],
) -> str | None:
    if not parts:
        doc = model_cls.__doc__ or ""
        return clean_description(doc.strip().splitlines()[0] if doc else None)

    field_name = str(parts[0])
    field_info = model_cls.model_fields.get(field_name)
    if field_info is None:
        if len(parts) == 1:
            return _union_variant_field_description(model_cls, field_name)
        return None
    if len(parts) == 1:
        return clean_description(field_info.description)

    list_model = _resolve_list_model_type(field_info.annotation)
    if list_model is not None:
        return model_description_for_path(list_model, parts[1:])

    nested_model = _resolve_model_type(field_info.annotation)
    if nested_model is not None:
        description = model_description_for_path(nested_model, parts[1:])
        if description:
            return description
        return _union_variant_description(field_info.annotation, parts[1:])
    return None


def root_config_description_for_path(parts: Sequence[str]) -> str | None:
    """Return a Pydantic description for one root simulation TOML path."""
    if not parts:
        return None
    key = str(parts[0])

    if len(parts) == 1:
        root_field = root_scalar_fields().get(key)
        if root_field is not None:
            return clean_description(root_field.description)

    section_model = root_sections().get(key)
    if section_model is None:
        return None
    if len(parts) == 1:
        doc = section_model.__doc__ or ""
        return clean_description(doc.strip().splitlines()[0] if doc else None)
    return model_description_for_path(section_model, parts[1:])


__all__ = [
    "clean_description",
    "model_description_for_path",
    "model_field_description",
    "root_config_description_for_path",
]
