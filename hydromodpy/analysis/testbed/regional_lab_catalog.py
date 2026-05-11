"""Site catalog loading for the regional-lab launcher family."""

from __future__ import annotations

import platform
import sys
from collections.abc import Mapping
from typing import Any

from hydromodpy.analysis.catalog import (
    CatalogLoadSpec,
    CatalogRow,
    detect_catalog_format,
    load_catalog_rows,
    normalize_float,
    normalize_required_field_names,
    normalize_tags,
    normalize_text,
    parse_bool,
)
from hydromodpy.analysis.testbed.regional_lab_config import RegionalLabCatalogConfig
from hydromodpy.analysis.testbed.regional_lab_types import RegionalLabSiteRecord


def normalize_platform_token(value: object) -> str | None:
    """Normalize one platform selector token."""
    text = normalize_text(value)
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


def current_platform_tokens() -> set[str]:
    """Return the normalized platform aliases supported by this runtime."""
    tokens: set[str] = set()
    for raw_value in (sys.platform, platform.system()):
        normalized = normalize_platform_token(raw_value)
        if normalized is not None:
            tokens.add(normalized)
    if "darwin" in tokens:
        tokens.update({"macos", "mac"})
    return tokens


def _site_from_mapping(
    row: CatalogRow | Mapping[str, Any],
    *,
    catalog_cfg: RegionalLabCatalogConfig,
) -> RegionalLabSiteRecord:
    """Build one typed site record from raw CSV or JSONL payload."""
    if isinstance(row, CatalogRow):
        raw = row.raw
        resolved_paths = row.resolved_paths
        tags_by_field = row.tags_by_field
    else:
        raw = {}
        for key, value in row.items():
            normalized_key = str(key).replace("\ufeff", "").strip().strip('"')
            if normalized_key:
                raw[normalized_key] = value
        resolved_paths = {}
        tags_by_field = {}

    missing_required_fields = normalize_required_field_names(
        raw,
        field_names=catalog_cfg.required_fields,
    )
    if missing_required_fields:
        raise ValueError(
            "regional-lab catalog row is missing required field(s): "
            + ", ".join(missing_required_fields)
        )

    site_id = normalize_text(raw.get(catalog_cfg.site_id_field))
    if site_id is None:
        raise ValueError(
            "regional-lab catalog row is missing the configured site identifier field "
            f"'{catalog_cfg.site_id_field}'"
        )

    enabled = True
    if catalog_cfg.enabled_field is not None and catalog_cfg.enabled_field in raw:
        enabled = parse_bool(raw[catalog_cfg.enabled_field])

    return RegionalLabSiteRecord(
        site_id=site_id,
        site_label=(
            None
            if catalog_cfg.site_label_field is None
            else normalize_text(raw.get(catalog_cfg.site_label_field))
        ),
        cluster_id=(
            None
            if catalog_cfg.cluster_id_field is None
            else normalize_text(raw.get(catalog_cfg.cluster_id_field))
        ),
        cluster_label=(
            None
            if catalog_cfg.cluster_label_field is None
            else normalize_text(raw.get(catalog_cfg.cluster_label_field))
        ),
        cluster_family=(
            None
            if catalog_cfg.cluster_family_field is None
            else normalize_text(raw.get(catalog_cfg.cluster_family_field))
        ),
        cluster_scale=(
            None
            if catalog_cfg.cluster_scale_field is None
            else normalize_text(raw.get(catalog_cfg.cluster_scale_field))
        ),
        region_id=(
            None
            if catalog_cfg.region_field is None
            else normalize_text(raw.get(catalog_cfg.region_field))
        ),
        source_selection_id=(
            None
            if catalog_cfg.source_selection_field is None
            else normalize_text(raw.get(catalog_cfg.source_selection_field))
        ),
        site_status=(
            None
            if catalog_cfg.status_field is None
            else normalize_text(raw.get(catalog_cfg.status_field))
        ),
        maturity=(
            None
            if catalog_cfg.maturity_field is None
            else normalize_text(raw.get(catalog_cfg.maturity_field))
        ),
        x=None if catalog_cfg.x_field is None else normalize_float(raw.get(catalog_cfg.x_field)),
        y=None if catalog_cfg.y_field is None else normalize_float(raw.get(catalog_cfg.y_field)),
        area_km2=(
            None
            if catalog_cfg.area_km2_field is None
            else normalize_float(raw.get(catalog_cfg.area_km2_field))
        ),
        site_tags=(
            ()
            if catalog_cfg.tags_field is None
            else tags_by_field.get(catalog_cfg.tags_field)
            or normalize_tags(raw.get(catalog_cfg.tags_field), separator=catalog_cfg.tag_separator)
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

    format_name = detect_catalog_format(
        catalog_cfg.path,
        declared_format=catalog_cfg.format,
    )
    if format_name not in {"csv", "jsonl"}:
        raise ValueError(f"Unsupported regional-lab catalog format: {format_name}")

    tag_fields = () if catalog_cfg.tags_field is None else (catalog_cfg.tags_field,)
    rows = load_catalog_rows(
        CatalogLoadSpec(
            path=catalog_cfg.path,
            format=format_name,
            required_fields=catalog_cfg.required_fields,
            path_fields=catalog_cfg.path_fields,
            tag_fields=tag_fields,
            tag_separator=catalog_cfg.tag_separator,
            allow_empty=True,
            source_label="regional-lab catalog",
        )
    )
    sites = [_site_from_mapping(row, catalog_cfg=catalog_cfg) for row in rows]

    if not sites:
        raise ValueError("regional-lab site catalog did not yield any site")

    seen_ids: set[str] = set()
    for site in sites:
        normalized = site.site_id.lower()
        if normalized in seen_ids:
            raise ValueError(f"Duplicate regional-lab site_id '{site.site_id}'")
        seen_ids.add(normalized)
    return sites
