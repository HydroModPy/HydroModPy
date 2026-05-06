"""Detect TOML paths whose payload schema is opaque to the doc generator.

The config reference is derived from Pydantic ``model_fields`` only. A
``dict[str, object]`` or ``dict[str, dict[str, object]]`` under
``HydroModPyConfig`` therefore means the schema has hidden structure,
unless the path is explicitly whitelisted as a free-form key/value
mapping in :data:`INTENTIONALLY_OPAQUE_PATHS`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel
from pydantic.fields import FieldInfo


@dataclass(frozen=True)
class UncoveredOpaqueField:
    """One TOML path whose dynamic payload schema is undocumented."""

    toml_path: str
    annotation: str


_OPAQUE_DICT_VALUE = re.compile(
    r"\bdict\[\s*str\s*,\s*(object|dict\[str,\s*object\])",
    re.IGNORECASE,
)


INTENTIONALLY_OPAQUE_PATHS: frozenset[str] = frozenset(
    {
        "mesh_catchment.hydraulic_properties.conductivity.values",
        "mesh_catchment.hydraulic_properties.storage_coefficient.values",
    }
)
"""TOML paths intentionally typed as ``dict[str, scalar]`` without a sub-model.

Each entry is a free-form mapping from an external key (geology zone,
station id, ...) to a scalar value. There is no payload schema to
document, so the coverage check skips them.
"""


def _format_annotation(field: FieldInfo) -> str:
    annotation = field.annotation
    if isinstance(annotation, type):
        return annotation.__name__
    return str(annotation)


def _looks_opaque(field: FieldInfo) -> bool:
    """Return True when ``field`` hides its sub-schema behind a generic container."""
    annotation_str = _format_annotation(field)
    return bool(_OPAQUE_DICT_VALUE.search(annotation_str))


def _walk_opaque_fields(
    model: type[BaseModel],
    section_path: str,
    *,
    seen: set[int] | None = None,
) -> list[tuple[str, str]]:
    """Recursively yield (toml_path, annotation) for every opaque field."""
    if seen is None:
        seen = {id(model)}
    out: list[tuple[str, str]] = []
    for field_name, field in model.model_fields.items():
        if getattr(field, "exclude", False):
            continue
        full_path = f"{section_path}.{field_name}" if section_path else field_name
        if _looks_opaque(field):
            out.append((full_path, _format_annotation(field)))
        annotation: Any = field.annotation
        candidates = [annotation]
        candidates.extend(getattr(annotation, "__args__", ()) or ())
        for arg in candidates:
            if isinstance(arg, type) and issubclass(arg, BaseModel) and id(arg) not in seen:
                out.extend(
                    _walk_opaque_fields(
                        arg,
                        full_path,
                        seen=seen | {id(arg)},
                    )
                )
    return out


def find_uncovered_opaque_fields(root_model: type[BaseModel]) -> list[UncoveredOpaqueField]:
    """Return opaque TOML paths that are not intentionally free-form.

    Two filters apply before the coverage check:

    - fields marked ``exclude=True`` are ignored (they are not part of
      the published schema, e.g. inherited generic containers);
    - paths registered in :data:`INTENTIONALLY_OPAQUE_PATHS` are
      whitelisted for free-form key/value mappings without a sub-model.
    """
    candidates = _walk_opaque_fields(root_model, section_path="")
    uncovered: list[UncoveredOpaqueField] = []
    for full_path, annotation in candidates:
        if full_path in INTENTIONALLY_OPAQUE_PATHS:
            continue
        uncovered.append(UncoveredOpaqueField(toml_path=full_path, annotation=annotation))
    return uncovered


__all__ = ["UncoveredOpaqueField", "find_uncovered_opaque_fields"]
