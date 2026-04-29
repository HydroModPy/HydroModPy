"""Site catalog loading for the regional-lab launcher family."""

from __future__ import annotations

import csv
import json
import platform
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from hydromodpy.analysis.batch.batch_types import (
    RegionalLabSiteRecord,
    _merge_tags,
    _normalize_float,
    _normalize_text,
)
from hydromodpy.analysis.batch.config import RegionalLabCatalogConfig


def _parse_bool(value: object) -> bool:
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


def _normalize_platform_token(value: object) -> str | None:
    """Normalize one platform selector token."""
    text = _normalize_text(value)
    if text is None:
        return None
    normalized = text.lower().replace("_", "-")
    if normalized in {"win32", "cygwin", "msys", "windows"}:
        return "windows"
    if normalized.startswith("linux"):
        return "linux"
    if normalized in {"darwin", "mac", "macos", "osx"}:
        return "darwin"
    return normalized


def _current_platform_tokens() -> set[str]:
    """Return the normalized platform aliases supported by this runtime."""
    tokens: set[str] = set()
    for raw_value in (sys.platform, platform.system()):
        normalized = _normalize_platform_token(raw_value)
        if normalized is not None:
            tokens.add(normalized)
    if "darwin" in tokens:
        tokens.update({"macos", "mac"})
    return tokens


def _normalize_tags(value: object, *, separator: str) -> tuple[str, ...]:
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
    return _merge_tags(tuple(str(item).strip() for item in raw_items if str(item).strip()))


def _detect_catalog_format(path: Path, *, declared_format: str) -> str:
    """Resolve the effective site-catalog format."""
    if declared_format != "auto":
        return declared_format
    suffix = path.suffix.strip().lower()
    if suffix == ".csv":
        return "csv"
    if suffix in {".jsonl", ".ndjson"}:
        return "jsonl"
    raise ValueError(
        "Unable to infer regional-lab catalog format from path. "
        "Set regional_lab.catalog.format explicitly to 'csv' or 'jsonl'."
    )


def _normalize_required_field_names(
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


def _resolve_catalog_path(
    *,
    catalog_path: Path,
    raw_value: object,
) -> str | None:
    """Resolve one optional path-like field relative to the catalog directory."""
    text = _normalize_text(raw_value)
    if text is None:
        return None
    path = Path(text).expanduser()
    if not path.is_absolute():
        path = catalog_path.parent / path
    return str(path.resolve())


def _site_from_mapping(
    mapping: Mapping[str, Any],
    *,
    catalog_cfg: RegionalLabCatalogConfig,
) -> RegionalLabSiteRecord:
    """Build one typed site record from raw CSV or JSONL payload."""
    raw: dict[str, Any] = {}
    for key, value in mapping.items():
        normalized_key = str(key).replace("\ufeff", "").strip().strip('"')
        if normalized_key == "":
            continue
        raw[normalized_key] = value

    missing_required_fields = _normalize_required_field_names(
        raw,
        field_names=catalog_cfg.required_fields,
    )
    if missing_required_fields:
        raise ValueError(
            "regional-lab catalog row is missing required field(s): "
            + ", ".join(missing_required_fields)
        )

    site_id = _normalize_text(raw.get(catalog_cfg.site_id_field))
    if site_id is None:
        raise ValueError(
            "regional-lab catalog row is missing the configured site identifier field "
            f"'{catalog_cfg.site_id_field}'"
        )

    resolved_paths: dict[str, str] = {}
    for field_name in catalog_cfg.path_fields:
        resolved = _resolve_catalog_path(
            catalog_path=catalog_cfg.path, raw_value=raw.get(field_name)
        )
        if resolved is not None:
            resolved_paths[field_name] = resolved

    enabled = True
    if catalog_cfg.enabled_field is not None and catalog_cfg.enabled_field in raw:
        enabled = _parse_bool(raw[catalog_cfg.enabled_field])

    return RegionalLabSiteRecord(
        site_id=site_id,
        site_label=(
            None
            if catalog_cfg.site_label_field is None
            else _normalize_text(raw.get(catalog_cfg.site_label_field))
        ),
        cluster_id=(
            None
            if catalog_cfg.cluster_id_field is None
            else _normalize_text(raw.get(catalog_cfg.cluster_id_field))
        ),
        cluster_label=(
            None
            if catalog_cfg.cluster_label_field is None
            else _normalize_text(raw.get(catalog_cfg.cluster_label_field))
        ),
        cluster_family=(
            None
            if catalog_cfg.cluster_family_field is None
            else _normalize_text(raw.get(catalog_cfg.cluster_family_field))
        ),
        cluster_scale=(
            None
            if catalog_cfg.cluster_scale_field is None
            else _normalize_text(raw.get(catalog_cfg.cluster_scale_field))
        ),
        region_id=(
            None
            if catalog_cfg.region_field is None
            else _normalize_text(raw.get(catalog_cfg.region_field))
        ),
        source_selection_id=(
            None
            if catalog_cfg.source_selection_field is None
            else _normalize_text(raw.get(catalog_cfg.source_selection_field))
        ),
        site_status=(
            None
            if catalog_cfg.status_field is None
            else _normalize_text(raw.get(catalog_cfg.status_field))
        ),
        maturity=(
            None
            if catalog_cfg.maturity_field is None
            else _normalize_text(raw.get(catalog_cfg.maturity_field))
        ),
        x=None if catalog_cfg.x_field is None else _normalize_float(raw.get(catalog_cfg.x_field)),
        y=None if catalog_cfg.y_field is None else _normalize_float(raw.get(catalog_cfg.y_field)),
        area_km2=(
            None
            if catalog_cfg.area_km2_field is None
            else _normalize_float(raw.get(catalog_cfg.area_km2_field))
        ),
        site_tags=(
            ()
            if catalog_cfg.tags_field is None
            else _normalize_tags(
                raw.get(catalog_cfg.tags_field),
                separator=catalog_cfg.tag_separator,
            )
        ),
        cluster_tags=(),
        enabled=enabled,
        resolved_paths=resolved_paths,
        raw=raw,
    )


def load_site_catalog(catalog_cfg: RegionalLabCatalogConfig) -> list[RegionalLabSiteRecord]:
    """Load one site catalog from CSV or JSONL."""
    if not catalog_cfg.path.exists():
        raise FileNotFoundError(f"regional_lab.catalog.path not found: {catalog_cfg.path}")

    format_name = _detect_catalog_format(
        catalog_cfg.path,
        declared_format=catalog_cfg.format,
    )
    sites: list[RegionalLabSiteRecord] = []
    if format_name == "csv":
        with catalog_cfg.path.open("r", encoding="utf-8", newline="") as stream:
            reader = csv.DictReader(stream)
            for row in reader:
                sites.append(_site_from_mapping(row, catalog_cfg=catalog_cfg))
    elif format_name == "jsonl":
        with catalog_cfg.path.open("r", encoding="utf-8") as stream:
            for line_number, raw_line in enumerate(stream, start=1):
                line = raw_line.strip()
                if line == "":
                    continue
                payload = json.loads(line)
                if not isinstance(payload, Mapping):
                    raise ValueError(
                        f"regional-lab catalog JSONL line {line_number} must be an object"
                    )
                sites.append(_site_from_mapping(payload, catalog_cfg=catalog_cfg))
    else:
        raise ValueError(f"Unsupported regional-lab catalog format: {format_name}")

    if not sites:
        raise ValueError("regional-lab site catalog did not yield any site")

    seen_ids: set[str] = set()
    for site in sites:
        normalized = site.site_id.lower()
        if normalized in seen_ids:
            raise ValueError(f"Duplicate regional-lab site_id '{site.site_id}'")
        seen_ids.add(normalized)
    return sites
