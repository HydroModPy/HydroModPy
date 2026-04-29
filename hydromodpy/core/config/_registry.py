"""Single source of truth for HydroModPy root TOML sections.

The registry is derived from ``HydroModPyConfig.model_fields`` so callers
that need to enumerate root sections (TOML scaffolding, JSON Schema export,
interactive UI) stay automatically in sync with the root model.
"""

from __future__ import annotations

import types as _stdlib_types
import typing
from typing import get_args, get_origin

from pydantic import BaseModel

_CACHE: dict[str, type[BaseModel]] | None = None


def _is_union_origin(origin: object) -> bool:
    if origin is typing.Union:
        return True
    if hasattr(_stdlib_types, "UnionType") and origin is _stdlib_types.UnionType:
        return True
    return False


def _resolve_basemodel(annotation: object) -> type[BaseModel] | None:
    """Return the concrete BaseModel class behind X / Optional[X], or None."""
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return annotation
    if not _is_union_origin(get_origin(annotation)):
        return None
    for arg in get_args(annotation):
        if isinstance(arg, type) and issubclass(arg, BaseModel):
            return arg
    return None


def root_sections() -> dict[str, type[BaseModel]]:
    """Return the map of root TOML section names to Pydantic model classes.

    Iterates ``HydroModPyConfig.model_fields`` in declaration order and
    keeps only fields whose annotation resolves to a ``BaseModel`` subclass
    (scalars such as the ``workflow`` literal are skipped). Returns a fresh
    dict on each call so callers can safely mutate it.
    """
    global _CACHE
    if _CACHE is None:
        from hydromodpy.core.config.hydromodpy_config import HydroModPyConfig

        result: dict[str, type[BaseModel]] = {}
        for name, info in HydroModPyConfig.model_fields.items():
            cls = _resolve_basemodel(info.annotation)
            if cls is not None:
                result[name] = cls
        _CACHE = result
    return dict(_CACHE)


__all__ = ["root_sections"]
