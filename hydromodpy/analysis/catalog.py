"""Common catalog primitives for campaign-oriented analysis workflows."""

from __future__ import annotations

import csv
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SUPPORTED_CATALOG_FORMATS = {"auto", "csv", "jsonl"}


def normalize_text(value: object) -> str | None:
    """Return one stripped optional text value."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def normalize_float(value: object) -> float | None:
    """Return one optional float-like value."""
    text = normalize_text(value)
    if text is None:
        return None
    return float(text)


def parse_bool(value: object) -> bool:
    """Parse common string/number bool representations."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off", ""}:
        return False
    raise ValueError(f"Unsupported boolean value: {value!r}")


def merge_tags(*tag_groups: Sequence[str]) -> tuple[str, ...]:
    """Merge multiple tag groups while preserving the first-seen casing."""
    merged: list[str] = []
    seen: set[str] = set()
    for group in tag_groups:
        for raw_item in group:
            item = str(raw_item).strip()
            if item == "":
                continue
            normalized = item.lower()
            if normalized in seen:
                continue
            seen.add(normalized)
            merged.append(item)
    return tuple(merged)


def normalize_tags(value: object, *, separator: str) -> tuple[str, ...]:
    """Normalize tags from CSV or JSONL payloads."""
    if value is None:
        return ()
    if isinstance(value, (list, tuple)):
        raw_items = value
    else:
        text = str(value).strip()
        if text == "":
            return ()
        raw_items = text.split(separator)
    return merge_tags(tuple(str(item).strip() for item in raw_items if str(item).strip()))


def detect_catalog_format(path: Path, *, declared_format: str) -> str:
    """Resolve the effective catalog format from a declaration and suffix."""
    if declared_format != "auto":
        return declared_format
    suffix = path.suffix.strip().lower()
    if suffix == ".csv":
        return "csv"
    if suffix in {".jsonl", ".ndjson"}:
        return "jsonl"
    raise ValueError(
        "Unable to infer catalog format from path. "
        "Set catalog.format explicitly to 'csv' or 'jsonl'."
    )


def normalize_required_field_names(
    mapping: Mapping[str, Any],
    *,
    field_names: Sequence[str],
) -> tuple[str, ...]:
    """Return the subset of required fields that are missing from one mapping."""
    missing: list[str] = []
    for field_name in field_names:
        value = mapping.get(field_name)
        if value is None:
            missing.append(field_name)
            continue
        if isinstance(value, str) and value.strip() == "":
            missing.append(field_name)
    return tuple(missing)


def resolve_catalog_path(
    *,
    catalog_path: Path,
    raw_value: object,
) -> str | None:
    """Resolve one optional path-like field relative to the catalog directory."""
    text = normalize_text(raw_value)
    if text is None:
        return None
    path = Path(text).expanduser()
    if not path.is_absolute():
        path = catalog_path.parent / path
    return str(path.resolve())


def normalize_catalog_mapping(mapping: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize raw CSV/JSONL row keys while preserving row values."""
    raw: dict[str, Any] = {}
    for key, value in mapping.items():
        normalized_key = str(key).replace("\ufeff", "").strip().strip('"')
        if normalized_key == "":
            continue
        raw[normalized_key] = value
    return raw


@dataclass(frozen=True)
class CatalogLoadSpec:
    """Generic CSV/JSONL catalog-loading contract."""

    path: Path
    format: str = "auto"
    required_fields: tuple[str, ...] = ()
    path_fields: tuple[str, ...] = ()
    tag_fields: tuple[str, ...] = ()
    tag_separator: str = ";"
    unique_field: str | None = None
    allow_empty: bool = False
    source_label: str = "catalog"


@dataclass(frozen=True)
class CatalogRow:
    """One normalized row loaded from a campaign catalog."""

    raw: dict[str, Any]
    resolved_paths: dict[str, str]
    tags_by_field: dict[str, tuple[str, ...]]
    source_index: int

    @property
    def tags(self) -> tuple[str, ...]:
        """Return all normalized tags carried by configured tag fields."""
        return merge_tags(*self.tags_by_field.values())

    def build_template_context(self, *, tag_separator: str = ";") -> dict[str, Any]:
        """Return a formatting context with resolved paths and normalized tags."""
        context = dict(self.raw)
        context.update(self.resolved_paths)
        for field_name, tags in self.tags_by_field.items():
            context[field_name] = tag_separator.join(tags)
        return context


@dataclass(frozen=True)
class CatalogRowSelector:
    """Generic row selector shared by catalog-backed campaign workflows."""

    field_equals: tuple[tuple[str, str], ...] = ()
    tags: tuple[str, ...] = ()
    exclude_tags: tuple[str, ...] = ()
    enabled_field: str | None = None
    include_disabled: bool = False
    limit: int | None = None


def _row_from_mapping(
    mapping: Mapping[str, Any],
    *,
    spec: CatalogLoadSpec,
    source_index: int,
) -> CatalogRow:
    raw = normalize_catalog_mapping(mapping)
    missing_required_fields = normalize_required_field_names(
        raw,
        field_names=spec.required_fields,
    )
    if missing_required_fields:
        raise ValueError(
            f"{spec.source_label} row is missing required field(s): "
            + ", ".join(missing_required_fields)
        )

    resolved_paths: dict[str, str] = {}
    for field_name in spec.path_fields:
        resolved = resolve_catalog_path(catalog_path=spec.path, raw_value=raw.get(field_name))
        if resolved is not None:
            resolved_paths[field_name] = resolved

    tags_by_field: dict[str, tuple[str, ...]] = {}
    for field_name in spec.tag_fields:
        tags_by_field[field_name] = normalize_tags(
            raw.get(field_name),
            separator=spec.tag_separator,
        )

    return CatalogRow(
        raw=raw,
        resolved_paths=resolved_paths,
        tags_by_field=tags_by_field,
        source_index=source_index,
    )


def load_catalog_rows(spec: CatalogLoadSpec) -> list[CatalogRow]:
    """Load normalized rows from a CSV or JSONL catalog."""
    if spec.format not in SUPPORTED_CATALOG_FORMATS:
        raise ValueError(
            f"Unsupported {spec.source_label} format: {spec.format}. "
            "Use 'auto', 'csv', or 'jsonl'."
        )
    if not spec.path.exists():
        raise FileNotFoundError(f"{spec.source_label} path not found: {spec.path}")

    format_name = detect_catalog_format(spec.path, declared_format=spec.format)
    rows: list[CatalogRow] = []
    if format_name == "csv":
        with spec.path.open("r", encoding="utf-8", newline="") as stream:
            reader = csv.DictReader(stream)
            for index, row in enumerate(reader, start=1):
                rows.append(_row_from_mapping(row, spec=spec, source_index=index))
    elif format_name == "jsonl":
        with spec.path.open("r", encoding="utf-8") as stream:
            for line_number, raw_line in enumerate(stream, start=1):
                line = raw_line.strip()
                if line == "":
                    continue
                payload = json.loads(line)
                if not isinstance(payload, Mapping):
                    raise ValueError(
                        f"{spec.source_label} JSONL line {line_number} must be an object"
                    )
                rows.append(_row_from_mapping(payload, spec=spec, source_index=line_number))
    else:
        raise ValueError(f"Unsupported {spec.source_label} format: {format_name}")

    if not rows and not spec.allow_empty:
        raise ValueError(f"{spec.source_label} did not yield any row")

    if spec.unique_field is not None:
        seen: set[str] = set()
        for row in rows:
            value = normalize_text(row.raw.get(spec.unique_field))
            if value is None:
                continue
            normalized = value.lower()
            if normalized in seen:
                raise ValueError(
                    f"Duplicate {spec.source_label} {spec.unique_field} '{value}'"
                )
            seen.add(normalized)
    return rows


def row_matches_selector(row: CatalogRow, *, selector: CatalogRowSelector) -> bool:
    """Return whether one generic catalog row matches a selector."""
    if selector.enabled_field is not None and not selector.include_disabled:
        if selector.enabled_field in row.raw and not parse_bool(row.raw[selector.enabled_field]):
            return False

    for field_name, expected_value in selector.field_equals:
        actual_value = normalize_text(row.raw.get(field_name))
        if (actual_value or "").lower() != expected_value.lower():
            return False

    row_tags = {item.lower() for item in row.tags}
    if selector.tags and not {item.lower() for item in selector.tags}.issubset(row_tags):
        return False
    if selector.exclude_tags and row_tags.intersection(
        {item.lower() for item in selector.exclude_tags}
    ):
        return False
    return True


def select_catalog_rows(
    rows: Sequence[CatalogRow],
    *,
    selector: CatalogRowSelector,
) -> list[CatalogRow]:
    """Filter catalog rows while preserving source order."""
    selected = [row for row in rows if row_matches_selector(row, selector=selector)]
    if selector.limit is not None:
        return selected[: int(selector.limit)]
    return selected
