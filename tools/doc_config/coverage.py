"""Detect TOML paths whose payload schema is opaque to the doc generator.

A *dispatcher candidate* is one Pydantic field whose annotation hides its
real sub-schema behind a generic container, typically:

- ``dict[str, object]``: the parent stores raw payloads validated at
  runtime by a separate normalizer (``[flow.bc.<id>]``).
- ``dict[str, dict[str, object]]``: same idea with a second-level dict
  (``[flow.param.<id>]`` whose payloads use the field-param grammar).
- ``list[<NonBaseModel>]``: a list of payloads where the element type is
  not a ``BaseModel`` so the recursive renderer cannot drill in.

For these cases the generator cannot derive the sub-table schema from
``model_fields`` alone. The convention is to declare each one in
:mod:`tools.doc_config.dispatchers` so the doc rendering picks up the
dedicated payload model and emits a "Dynamic sub-tables" entry.

This module compares the candidate set discovered by walking
:class:`HydroModPyConfig` against the entries registered in
:mod:`tools.doc_config.dispatchers` and reports any path that lacks
coverage. The doc generator emits one warning per uncovered path during
the Sphinx build, so a forgotten dispatcher fails loudly instead of
silently producing an incomplete reference page.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel
from pydantic.fields import FieldInfo

from tools.doc_config.dispatchers import all_dispatchers


@dataclass(frozen=True)
class UncoveredDispatcher:
    """One TOML path whose dynamic payload schema is undocumented."""

    toml_path: str
    annotation: str


_OPAQUE_DICT_VALUE = re.compile(
    r"\bdict\[\s*str\s*,\s*(object|dict\[str,\s*object\])",
    re.IGNORECASE,
)


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


def _normalize_pattern(pattern: str) -> str:
    """Strip TOML brackets and the ``<id>`` placeholder from a pattern."""
    text = pattern.strip()
    text = text.replace("[[", "").replace("]]", "")
    text = text.strip("[]")
    text = re.sub(r"\.<[^>]+>.*$", "", text)
    text = re.sub(r"\s.*$", "", text)
    return text


def find_uncovered_dispatchers(root_model: type[BaseModel]) -> list[UncoveredDispatcher]:
    """Return opaque TOML paths missing from ``dispatchers.py``."""
    covered_prefixes = {_normalize_pattern(entry.pattern) for entry in all_dispatchers()}
    candidates = _walk_opaque_fields(root_model, section_path="")
    uncovered: list[UncoveredDispatcher] = []
    for full_path, annotation in candidates:
        if any(
            full_path == prefix or full_path.startswith(prefix + ".") for prefix in covered_prefixes
        ):
            continue
        uncovered.append(UncoveredDispatcher(toml_path=full_path, annotation=annotation))
    return uncovered


__all__ = ["UncoveredDispatcher", "find_uncovered_dispatchers"]
