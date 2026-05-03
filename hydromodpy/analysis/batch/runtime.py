"""Launcher family for regional site-cluster laboratories."""

from __future__ import annotations

import csv
import json
import math
import platform
import subprocess
import sys
import time
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hydromodpy.analysis.batch.config import (
    RegionalLabCatalogConfig,
    RegionalLabClusterRuleConfig,
    RegionalLabConfig,
    RegionalLabRecipeConfig,
    RegionalLabSelectionConfig,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


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


def _normalize_text(value: object) -> str | None:
    """Return one stripped optional text value."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_float(value: object) -> float | None:
    """Return one optional float-like value."""
    text = _normalize_text(value)
    if text is None:
        return None
    return float(text)


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


def _merge_tags(*tag_groups: Sequence[str]) -> tuple[str, ...]:
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


@dataclass(frozen=True)
class RegionalLabSiteRecord:
    """One site selected from the regional-lab catalog."""

    site_id: str
    site_label: str | None
    cluster_id: str | None
    cluster_label: str | None
    cluster_family: str | None
    cluster_scale: str | None
    region_id: str | None
    source_selection_id: str | None
    site_status: str | None
    maturity: str | None
    x: float | None
    y: float | None
    area_km2: float | None
    site_tags: tuple[str, ...]
    cluster_tags: tuple[str, ...]
    enabled: bool
    resolved_paths: dict[str, str]
    raw: dict[str, Any]

    @property
    def tags(self) -> tuple[str, ...]:
        """Return effective site tags, including cluster-enrichment tags."""
        return _merge_tags(self.site_tags, self.cluster_tags)

    def to_summary_mapping(self) -> dict[str, Any]:
        """Serialize one site into a JSON-friendly payload."""
        return {
            "site_id": self.site_id,
            "site_label": self.site_label,
            "cluster_id": self.cluster_id,
            "cluster_label": self.cluster_label,
            "cluster_family": self.cluster_family,
            "cluster_scale": self.cluster_scale,
            "region_id": self.region_id,
            "source_selection_id": self.source_selection_id,
            "site_status": self.site_status,
            "maturity": self.maturity,
            "x": self.x,
            "y": self.y,
            "area_km2": self.area_km2,
            "site_tags": list(self.site_tags),
            "cluster_tags": list(self.cluster_tags),
            "tags": list(self.tags),
            "enabled": bool(self.enabled),
            "resolved_paths": dict(self.resolved_paths),
            "raw": dict(self.raw),
        }

    def to_inventory_mapping(self) -> dict[str, Any]:
        """Serialize one site into a flat inventory row."""
        return {
            "site_id": self.site_id,
            "site_label": self.site_label or "",
            "cluster_id": self.cluster_id or "",
            "cluster_label": self.cluster_label or "",
            "cluster_family": self.cluster_family or "",
            "cluster_scale": self.cluster_scale or "",
            "region_id": self.region_id or "",
            "source_selection_id": self.source_selection_id or "",
            "site_status": self.site_status or "",
            "maturity": self.maturity or "",
            "enabled": bool(self.enabled),
            "x": "" if self.x is None else self.x,
            "y": "" if self.y is None else self.y,
            "area_km2": "" if self.area_km2 is None else self.area_km2,
            "site_tags": ";".join(self.site_tags),
            "cluster_tags": ";".join(self.cluster_tags),
            "tags": ";".join(self.tags),
            "resolved_paths_json": json.dumps(self.resolved_paths, ensure_ascii=True),
        }

    def build_template_context(
        self,
        *,
        lab_id: str,
        recipe: RegionalLabRecipeConfig,
    ) -> dict[str, Any]:
        """Build the placeholder context used by one recipe."""
        context = dict(self.raw)
        context.update(self.resolved_paths)
        context.setdefault("site_id", self.site_id)
        context.setdefault("site_label", "" if self.site_label is None else self.site_label)
        context.setdefault("cluster_id", "" if self.cluster_id is None else self.cluster_id)
        context.setdefault(
            "cluster_label", "" if self.cluster_label is None else self.cluster_label
        )
        context.setdefault(
            "cluster_family", "" if self.cluster_family is None else self.cluster_family
        )
        context.setdefault(
            "cluster_scale", "" if self.cluster_scale is None else self.cluster_scale
        )
        context.setdefault("region_id", "" if self.region_id is None else self.region_id)
        context.setdefault(
            "source_selection_id",
            "" if self.source_selection_id is None else self.source_selection_id,
        )
        context.setdefault("site_status", "" if self.site_status is None else self.site_status)
        context.setdefault("maturity", "" if self.maturity is None else self.maturity)
        context.setdefault("x", "" if self.x is None else self.x)
        context.setdefault("y", "" if self.y is None else self.y)
        context.setdefault("area_km2", "" if self.area_km2 is None else self.area_km2)
        context["tags"] = ";".join(self.tags)
        context["lab_id"] = lab_id
        context["recipe_id"] = recipe.id
        context["recipe_label"] = recipe.label
        return context


@dataclass(frozen=True)
class RegionalLabPlannedCase:
    """One concrete launcher run planned from one site and one recipe."""

    case_id: str
    site: RegionalLabSiteRecord
    recipe_id: str
    recipe_label: str
    launcher: str
    config_path: Path

    def to_summary_mapping(self) -> dict[str, Any]:
        """Serialize one planned case into a JSON-friendly payload."""
        return {
            "case_id": self.case_id,
            "site_id": self.site.site_id,
            "site_label": self.site.site_label,
            "cluster_id": self.site.cluster_id,
            "cluster_label": self.site.cluster_label,
            "cluster_family": self.site.cluster_family,
            "cluster_scale": self.site.cluster_scale,
            "region_id": self.site.region_id,
            "site_status": self.site.site_status,
            "maturity": self.site.maturity,
            "site_tags": list(self.site.site_tags),
            "cluster_tags": list(self.site.cluster_tags),
            "tags": list(self.site.tags),
            "recipe_id": self.recipe_id,
            "recipe_label": self.recipe_label,
            "launcher": self.launcher,
            "config_path": str(self.config_path),
        }


@dataclass(frozen=True)
class RegionalLabSkippedCase:
    """One site x recipe pair skipped before launch because the contract is incomplete."""

    case_id: str
    site: RegionalLabSiteRecord
    recipe_id: str
    recipe_label: str
    launcher: str
    reason: str
    detail: str
    missing_fields: tuple[str, ...]
    config_path: Path | None

    def to_summary_mapping(self) -> dict[str, Any]:
        """Serialize one skipped site x recipe pair."""
        return {
            "case_id": self.case_id,
            "site_id": self.site.site_id,
            "site_label": self.site.site_label,
            "cluster_id": self.site.cluster_id,
            "cluster_label": self.site.cluster_label,
            "cluster_family": self.site.cluster_family,
            "cluster_scale": self.site.cluster_scale,
            "region_id": self.site.region_id,
            "site_status": self.site.site_status,
            "maturity": self.site.maturity,
            "tags": list(self.site.tags),
            "recipe_id": self.recipe_id,
            "recipe_label": self.recipe_label,
            "launcher": self.launcher,
            "reason": self.reason,
            "detail": self.detail,
            "missing_fields": list(self.missing_fields),
            "config_path": None if self.config_path is None else str(self.config_path),
        }


@dataclass(frozen=True)
class RegionalLabExecution:
    """Outcome recorded for one regional-lab case."""

    case: RegionalLabPlannedCase
    command: tuple[str, ...]
    status: str
    returncode: int | None
    duration_seconds: float | None
    reused_from_report: bool
    child_artifacts: dict[str, Any]


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


def _matches_text_filter(value: str | None, allowed: tuple[str, ...]) -> bool:
    """Return whether one optional text value matches one allowed-text filter."""
    if not allowed:
        return True
    normalized_value = "" if value is None else value.lower()
    return normalized_value in {item.lower() for item in allowed}


def _site_matches_selection(
    site: RegionalLabSiteRecord,
    *,
    selection: RegionalLabSelectionConfig,
) -> bool:
    """Return whether one site matches a set of selection filters."""
    if not selection.include_disabled and not site.enabled:
        return False
    if selection.site_ids and site.site_id.lower() not in {
        item.lower() for item in selection.site_ids
    }:
        return False
    if not _matches_text_filter(site.cluster_id, selection.cluster_ids):
        return False
    if not _matches_text_filter(site.region_id, selection.regions):
        return False
    if not _matches_text_filter(site.cluster_family, selection.families):
        return False
    if not _matches_text_filter(site.cluster_scale, selection.scales):
        return False
    if not _matches_text_filter(site.site_status, selection.statuses):
        return False
    if not _matches_text_filter(site.maturity, selection.maturity_levels):
        return False
    if selection.tags:
        site_tags = {item.lower() for item in site.tags}
        required_tags = {item.lower() for item in selection.tags}
        if not required_tags.issubset(site_tags):
            return False
    return True


def filter_sites(
    sites: Sequence[RegionalLabSiteRecord],
    *,
    selection: RegionalLabSelectionConfig,
) -> list[RegionalLabSiteRecord]:
    """Filter and stably sort site records."""
    selected = [site for site in sites if _site_matches_selection(site, selection=selection)]
    selected.sort(
        key=lambda site: (
            "" if site.region_id is None else site.region_id.lower(),
            "" if site.cluster_id is None else site.cluster_id.lower(),
            site.site_id.lower(),
        )
    )
    if selection.limit is not None:
        return selected[: int(selection.limit)]
    return selected


def _rule_matches_site(
    site: RegionalLabSiteRecord,
    *,
    rule: RegionalLabClusterRuleConfig,
) -> bool:
    """Return whether one cluster-enrichment rule applies to one site."""
    if not _site_matches_selection(site, selection=rule.selection):
        return False
    for field_name, expected_value in rule.field_equals:
        actual_value = _normalize_text(site.raw.get(field_name))
        if (actual_value or "").lower() != expected_value.lower():
            return False
    return True


def apply_cluster_rules(
    sites: Sequence[RegionalLabSiteRecord],
    *,
    cluster_rules: Sequence[RegionalLabClusterRuleConfig],
) -> list[RegionalLabSiteRecord]:
    """Apply explicit cluster-enrichment rules on top of raw catalog rows."""
    ordered_rules = sorted(
        (rule for rule in cluster_rules if rule.enabled),
        key=lambda rule: (int(rule.priority), rule.id.lower()),
    )
    if not ordered_rules:
        return list(sites)

    enriched_sites: list[RegionalLabSiteRecord] = []
    for site in sites:
        current = site
        for rule in ordered_rules:
            if not _rule_matches_site(current, rule=rule):
                continue
            can_override_cluster = rule.override_existing_cluster or current.cluster_id is None
            can_override_label = rule.override_existing_cluster or current.cluster_label is None
            can_override_family = rule.override_existing_cluster or current.cluster_family is None
            can_override_scale = rule.override_existing_cluster or current.cluster_scale is None
            current = replace(
                current,
                cluster_id=(
                    rule.set_cluster_id
                    if rule.set_cluster_id is not None and can_override_cluster
                    else current.cluster_id
                ),
                cluster_label=(
                    rule.set_cluster_label
                    if rule.set_cluster_label is not None and can_override_label
                    else current.cluster_label
                ),
                cluster_family=(
                    rule.set_cluster_family
                    if rule.set_cluster_family is not None and can_override_family
                    else current.cluster_family
                ),
                cluster_scale=(
                    rule.set_cluster_scale
                    if rule.set_cluster_scale is not None and can_override_scale
                    else current.cluster_scale
                ),
                cluster_tags=_merge_tags(current.cluster_tags, rule.cluster_tags),
            )
        enriched_sites.append(current)
    return enriched_sites


def _render_recipe_config_path(
    *,
    cfg: RegionalLabConfig,
    site: RegionalLabSiteRecord,
    recipe: RegionalLabRecipeConfig,
) -> Path:
    """Render and resolve one concrete config path for a site x recipe pair."""
    context = site.build_template_context(lab_id=cfg.lab_id, recipe=recipe)
    try:
        rendered = recipe.config_path_template.format_map(context)
    except KeyError as exc:
        missing_key = str(exc).strip("'")
        raise ValueError(
            f"regional_lab.recipe[{recipe.id}] references unknown template key '{missing_key}'"
        ) from exc
    path = Path(rendered).expanduser()
    if not path.is_absolute():
        path = cfg.base_dir / path
    return path.resolve()


def _evaluate_recipe_site(
    *,
    cfg: RegionalLabConfig,
    site: RegionalLabSiteRecord,
    recipe: RegionalLabRecipeConfig,
) -> tuple[RegionalLabPlannedCase | None, RegionalLabSkippedCase | None]:
    """Expand or skip one site x recipe pair depending on contract completeness."""
    case_id = f"{recipe.id}::{site.site_id}"
    context = site.build_template_context(lab_id=cfg.lab_id, recipe=recipe)
    if recipe.allowed_platforms:
        current_platforms = _current_platform_tokens()
        allowed_platforms = {
            normalized
            for item in recipe.allowed_platforms
            if (normalized := _normalize_platform_token(item)) is not None
        }
        if allowed_platforms and current_platforms.isdisjoint(allowed_platforms):
            return None, RegionalLabSkippedCase(
                case_id=case_id,
                site=site,
                recipe_id=recipe.id,
                recipe_label=recipe.label,
                launcher=recipe.launcher,
                reason="unsupported_platform",
                detail=(
                    "Recipe only supports platform(s): "
                    + ", ".join(sorted(allowed_platforms))
                    + f". Current platform: {', '.join(sorted(current_platforms))}"
                ),
                missing_fields=(),
                config_path=None,
            )
    missing_fields = _normalize_required_field_names(
        context,
        field_names=recipe.required_fields,
    )
    if missing_fields:
        return None, RegionalLabSkippedCase(
            case_id=case_id,
            site=site,
            recipe_id=recipe.id,
            recipe_label=recipe.label,
            launcher=recipe.launcher,
            reason="missing_required_fields",
            detail="Missing required field(s): " + ", ".join(missing_fields),
            missing_fields=missing_fields,
            config_path=None,
        )

    config_path = _render_recipe_config_path(cfg=cfg, site=site, recipe=recipe)
    if cfg.validate_config_paths and not config_path.exists():
        return None, RegionalLabSkippedCase(
            case_id=case_id,
            site=site,
            recipe_id=recipe.id,
            recipe_label=recipe.label,
            launcher=recipe.launcher,
            reason="missing_config_path",
            detail=f"Resolved child config is missing: {config_path}",
            missing_fields=(),
            config_path=config_path,
        )

    return (
        RegionalLabPlannedCase(
            case_id=case_id,
            site=site,
            recipe_id=recipe.id,
            recipe_label=recipe.label,
            launcher=recipe.launcher,
            config_path=config_path,
        ),
        None,
    )


def build_regional_lab_plan(
    cfg: RegionalLabConfig,
    sites: list[RegionalLabSiteRecord],
) -> tuple[
    list[RegionalLabSiteRecord],
    list[RegionalLabPlannedCase],
    list[RegionalLabSkippedCase],
]:
    """Expand the selected sites and recipes into concrete launcher runs."""
    enriched_sites = apply_cluster_rules(sites, cluster_rules=cfg.cluster_rules)
    selected_sites = filter_sites(enriched_sites, selection=cfg.selection)
    planned_cases: list[RegionalLabPlannedCase] = []
    skipped_cases: list[RegionalLabSkippedCase] = []

    for recipe in cfg.recipes:
        if not recipe.enabled:
            continue
        recipe_sites = filter_sites(
            selected_sites,
            selection=recipe.selection,
        )
        for site in recipe_sites:
            planned_case, skipped_case = _evaluate_recipe_site(
                cfg=cfg,
                site=site,
                recipe=recipe,
            )
            if skipped_case is not None:
                skipped_cases.append(skipped_case)
                continue
            if planned_case is not None:
                planned_cases.append(planned_case)

    if not selected_sites:
        raise ValueError("regional_lab selection did not match any site")
    if not planned_cases and not skipped_cases:
        raise ValueError("regional_lab did not expand any runnable or explainable case")
    return selected_sites, planned_cases, skipped_cases


def build_run_command(
    case: RegionalLabPlannedCase,
    *,
    python_executable: Path,
) -> list[str]:
    """Build one child launcher command."""
    if case.launcher == "simulation":
        return [
            str(python_executable),
            "-m",
            "launchers",
            "simulation",
            str(case.config_path),
        ]
    if case.launcher == "method-comparison":
        return [
            str(python_executable),
            "-m",
            "launchers",
            "method-comparison",
            "run",
            str(case.config_path),
        ]
    raise ValueError(f"Unsupported regional-lab launcher: {case.launcher}")


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    """Write one JSON payload to disk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )


def _csv_cell(value: object) -> str:
    """Serialize one CSV cell value."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (list, tuple, dict)):
        return json.dumps(value, ensure_ascii=True)
    return str(value)


def _write_csv_rows(
    path: Path,
    *,
    fieldnames: Sequence[str],
    rows: Sequence[Mapping[str, Any]],
) -> None:
    """Persist one flat CSV file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(fieldnames))
        writer.writeheader()
        for row in rows:
            writer.writerow({field: _csv_cell(row.get(field)) for field in fieldnames})


def _collect_fieldnames(rows: Sequence[Mapping[str, Any]]) -> list[str]:
    """Collect CSV fieldnames in first-seen order across heterogeneous rows."""
    out: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row.keys():
            text = str(key)
            if text in seen:
                continue
            seen.add(text)
            out.append(text)
    return out


def _read_json_file_if_exists(path: Path) -> dict[str, Any] | None:
    """Load one JSON file when it exists and is valid."""
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, Mapping):
        return None
    return dict(payload)


def _safe_float(value: object) -> float | None:
    """Return one finite float or ``None`` when unavailable."""
    try:
        out = float(value)
    except Exception:
        return None
    if not math.isfinite(out):
        return None
    return out


def _extract_simulation_child_artifacts(config_path: Path) -> dict[str, Any]:
    """Extract compact simulation artifacts from one child launcher config."""
    from hydromodpy.config import HydroModPyConfig
    from hydromodpy.core.workspace.path_registry import WorkspacePathRegistry

    artifacts: dict[str, Any] = {
        "child_artifact_kind": "simulation",
        "child_artifact_status": "unavailable",
    }
    try:
        cfg = HydroModPyConfig.from_toml(config_path)
    except Exception as exc:
        artifacts["child_artifact_status"] = "config_parse_failed"
        artifacts["child_artifact_error_type"] = type(exc).__name__
        artifacts["child_artifact_error_message"] = str(exc)
        return artifacts

    paths = WorkspacePathRegistry.from_config(cfg.workspace)
    run_id = str(cfg.simulation.run_id or config_path.stem)
    run_folder = paths.run_folder(run_id).resolve()
    simulations_root = paths.solver_scratch_folder.resolve()
    artifacts.update(
        {
            "child_artifact_status": "resolved",
            "child_project_root": str(paths.project_root.resolve()),
            "child_output_root": str(paths._effective_output_root.resolve()),
            "child_run_id": run_id,
            "child_run_folder": str(run_folder),
        }
    )

    metrics_path = run_folder / "_metrics.json"
    metrics_payload = _read_json_file_if_exists(metrics_path)
    if metrics_payload is not None:
        artifacts["child_metrics_json"] = str(metrics_path.resolve())
        artifacts["child_wall_time_seconds"] = _safe_float(metrics_payload.get("wall_time_seconds"))
        artifacts["child_success"] = metrics_payload.get("success")
        artifacts["child_mesh_output_mesh"] = _normalize_text(
            metrics_payload.get("mesh_output_mesh")
        )
        artifacts["child_mesh_output_exchange_bundle_dir"] = _normalize_text(
            metrics_payload.get("mesh_output_exchange_bundle_dir")
        )

    summary_candidates = sorted(
        simulations_root.rglob("_boussinesq_summary.json"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    if summary_candidates:
        summary_path = summary_candidates[0]
        summary_payload = _read_json_file_if_exists(summary_path)
        if summary_payload is not None:
            artifacts["child_boussinesq_summary_json"] = str(summary_path.resolve())
            artifacts["child_runtime_backend"] = _normalize_text(
                summary_payload.get("runtime_backend")
            )
            artifacts["child_runtime_engine"] = _normalize_text(
                summary_payload.get("runtime_engine")
            )
            artifacts["child_n_cells"] = summary_payload.get("n_cells")
            artifacts["child_solve_stage"] = _normalize_text(summary_payload.get("solve_stage"))
            artifacts["child_steady_residual_norm_inf"] = _safe_float(
                summary_payload.get("steady_residual_norm_inf")
            )
            artifacts["child_steady_nonlinear_iterations"] = summary_payload.get(
                "steady_nonlinear_iterations"
            )
            artifacts["child_surface_peak_active_fraction"] = _safe_float(
                summary_payload.get("surface_threshold_peak_active_fraction")
            )
            artifacts["child_surface_final_total_m3_day"] = _safe_float(
                summary_payload.get("surface_threshold_final_total_m3_day")
            )

    return artifacts


def _extract_method_comparison_child_artifacts(config_path: Path) -> dict[str, Any]:
    """Extract compact method-comparison artifacts from one child launcher config."""
    from hydromodpy.analysis.comparison.config import MethodComparisonConfig
    from hydromodpy.core.config.toml_loader import load_toml_with_base_config

    artifacts: dict[str, Any] = {
        "child_artifact_kind": "method_comparison",
        "child_artifact_status": "unavailable",
    }
    try:
        payload = load_toml_with_base_config(config_path)
        cfg = MethodComparisonConfig.from_toml(payload, config_path=config_path)
    except Exception as exc:
        artifacts["child_artifact_status"] = "config_parse_failed"
        artifacts["child_artifact_error_type"] = type(exc).__name__
        artifacts["child_artifact_error_message"] = str(exc)
        return artifacts

    comparison_root = cfg.comparison_root.resolve()
    artifacts.update(
        {
            "child_artifact_status": "resolved",
            "child_comparison_root": str(comparison_root),
        }
    )

    manifest_path = comparison_root / "comparison_manifest.json"
    manifest_payload = _read_json_file_if_exists(manifest_path)
    if manifest_payload is not None:
        artifacts["child_comparison_manifest_json"] = str(manifest_path.resolve())
        artifacts["child_wall_time_seconds"] = _safe_float(
            manifest_payload.get("wall_time_seconds")
        )
        artifacts["child_comparison_id"] = _normalize_text(manifest_payload.get("comparison_id"))
        artifacts["child_reference_variant"] = _normalize_text(
            manifest_payload.get("reference_variant")
        )
        artifacts["child_n_metric_rows"] = manifest_payload.get("n_metric_rows")
        artifacts["child_n_difference_rows"] = manifest_payload.get("n_difference_rows")
        artifacts["child_n_observable_rows"] = manifest_payload.get("n_observable_rows")
        variants = manifest_payload.get("variants")
        if isinstance(variants, list):
            completed_count = 0
            failed_count = 0
            for item in variants:
                if not isinstance(item, Mapping):
                    continue
                status = str(item.get("status", "")).strip().lower()
                if status in {"completed", "ok", "success"}:
                    completed_count += 1
                if status in {"failed", "error", "run_failed", "observable_extraction_failed"}:
                    failed_count += 1
            artifacts["child_variant_count"] = len(variants)
            artifacts["child_completed_variant_count"] = completed_count
            artifacts["child_failed_variant_count"] = failed_count

    metrics_path = comparison_root / "comparison_metrics.json"
    metrics_payload = _read_json_file_if_exists(metrics_path)
    if metrics_payload is not None:
        artifacts["child_comparison_metrics_json"] = str(metrics_path.resolve())
        summary_rows = metrics_payload.get("summary")
        differences_rows = metrics_payload.get("differences")
        if isinstance(summary_rows, list):
            rmse_values = [
                value
                for item in summary_rows
                if isinstance(item, Mapping)
                and (value := _safe_float(item.get("rmse"))) is not None
            ]
            mae_values = [
                value
                for item in summary_rows
                if isinstance(item, Mapping) and (value := _safe_float(item.get("mae"))) is not None
            ]
            artifacts["child_summary_metric_row_count"] = len(summary_rows)
            artifacts["child_summary_max_rmse"] = None if not rmse_values else max(rmse_values)
            artifacts["child_summary_max_mae"] = None if not mae_values else max(mae_values)
        if isinstance(differences_rows, list):
            artifacts["child_difference_metric_row_count"] = len(differences_rows)

    return artifacts


def _extract_child_case_artifacts(case: RegionalLabPlannedCase) -> dict[str, Any]:
    """Extract launcher-specific child artifacts for one planned case."""
    if case.launcher == "simulation":
        return _extract_simulation_child_artifacts(case.config_path)
    if case.launcher == "method-comparison":
        return _extract_method_comparison_child_artifacts(case.config_path)
    return {
        "child_artifact_kind": case.launcher,
        "child_artifact_status": "unsupported_launcher",
    }


def _build_plan_payload(
    *,
    cfg: RegionalLabConfig,
    selected_sites: list[RegionalLabSiteRecord],
    planned_cases: list[RegionalLabPlannedCase],
    skipped_cases: list[RegionalLabSkippedCase],
) -> dict[str, Any]:
    """Build one JSON-serializable execution plan."""
    return {
        "schema_version": "regional_lab_plan_v2",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "lab_id": cfg.lab_id,
        "config_path": str(cfg.config_path),
        "site_catalog_path": str(cfg.catalog.path),
        "output_root": str(cfg.output_root),
        "selected_site_count": len(selected_sites),
        "planned_case_count": len(planned_cases),
        "skipped_case_count": len(skipped_cases),
        "selected_sites": [site.to_summary_mapping() for site in selected_sites],
        "cluster_rules": [
            {
                "id": rule.id,
                "label": rule.label,
                "enabled": bool(rule.enabled),
                "priority": int(rule.priority),
                "field_equals": dict(rule.field_equals),
                "set_cluster_id": rule.set_cluster_id,
                "set_cluster_label": rule.set_cluster_label,
                "set_cluster_family": rule.set_cluster_family,
                "set_cluster_scale": rule.set_cluster_scale,
                "cluster_tags": list(rule.cluster_tags),
            }
            for rule in cfg.cluster_rules
        ],
        "recipes": [
            {
                "id": recipe.id,
                "label": recipe.label,
                "launcher": recipe.launcher,
                "enabled": bool(recipe.enabled),
                "config_path_template": recipe.config_path_template,
                "required_fields": list(recipe.required_fields),
                "allowed_platforms": list(recipe.allowed_platforms),
            }
            for recipe in cfg.recipes
        ],
        "cases": [case.to_summary_mapping() for case in planned_cases],
        "skipped_cases": [case.to_summary_mapping() for case in skipped_cases],
    }


def _execution_by_case_id(
    executions: Sequence[RegionalLabExecution],
) -> dict[str, RegionalLabExecution]:
    """Index execution rows by case identifier."""
    return {execution.case.case_id: execution for execution in executions}


def _build_recipe_summaries(
    *,
    cfg: RegionalLabConfig,
    selected_sites: Sequence[RegionalLabSiteRecord],
    planned_cases: Sequence[RegionalLabPlannedCase],
    skipped_cases: Sequence[RegionalLabSkippedCase],
    executions: Sequence[RegionalLabExecution],
) -> list[dict[str, Any]]:
    """Build one compact summary per recipe."""
    executions_by_case_id = _execution_by_case_id(executions)
    rows: list[dict[str, Any]] = []
    for recipe in cfg.recipes:
        if not recipe.enabled:
            continue
        candidate_sites = filter_sites(selected_sites, selection=recipe.selection)
        recipe_planned = [case for case in planned_cases if case.recipe_id == recipe.id]
        recipe_skipped = [case for case in skipped_cases if case.recipe_id == recipe.id]
        recipe_executions = [
            execution
            for case in recipe_planned
            if (execution := executions_by_case_id.get(case.case_id)) is not None
        ]
        execution_durations = [
            float(item.duration_seconds)
            for item in recipe_executions
            if item.duration_seconds is not None
        ]
        child_wall_times = [
            float(item.child_artifacts["child_wall_time_seconds"])
            for item in recipe_executions
            if _safe_float(item.child_artifacts.get("child_wall_time_seconds")) is not None
        ]
        executed_fresh = [item for item in recipe_executions if not item.reused_from_report]
        reused = [item for item in recipe_executions if item.reused_from_report]
        failed = [item for item in recipe_executions if item.status == "failed"]
        ok = [item for item in recipe_executions if item.status in {"ok", "skipped_existing_ok"}]
        pending_count = len(recipe_planned) - len(recipe_executions)
        rows.append(
            {
                "recipe_id": recipe.id,
                "recipe_label": recipe.label,
                "launcher": recipe.launcher,
                "candidate_site_count": len(candidate_sites),
                "planned_case_count": len(recipe_planned),
                "skipped_case_count": len(recipe_skipped),
                "executed_case_count": len(executed_fresh),
                "reused_case_count": len(reused),
                "successful_case_count": len(ok),
                "failed_case_count": len(failed),
                "pending_case_count": pending_count,
                "execution_duration_seconds_total": (
                    None if not execution_durations else round(sum(execution_durations), 6)
                ),
                "execution_duration_seconds_mean": (
                    None
                    if not execution_durations
                    else round(sum(execution_durations) / len(execution_durations), 6)
                ),
                "child_wall_time_seconds_total": (
                    None if not child_wall_times else round(sum(child_wall_times), 6)
                ),
                "coverage_ratio": (
                    0.0
                    if not candidate_sites
                    else round(len(recipe_planned) / len(candidate_sites), 6)
                ),
            }
        )
    return rows


def _build_group_summary(
    *,
    label: str,
    selected_sites: Sequence[RegionalLabSiteRecord],
    planned_cases: Sequence[RegionalLabPlannedCase],
    skipped_cases: Sequence[RegionalLabSkippedCase],
    executions: Sequence[RegionalLabExecution],
    extractor,
) -> list[dict[str, Any]]:
    """Build one compact summary by cluster, region, family, or scale."""
    execution_by_case_id = _execution_by_case_id(executions)
    groups: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            label: "",
            "site_count": 0,
            "planned_case_count": 0,
            "skipped_case_count": 0,
            "executed_case_count": 0,
            "reused_case_count": 0,
            "successful_case_count": 0,
            "failed_case_count": 0,
            "pending_case_count": 0,
        }
    )

    for site in selected_sites:
        key = extractor(site)
        row = groups[key]
        row[label] = key
        row["site_count"] += 1

    for case in planned_cases:
        key = extractor(case.site)
        row = groups[key]
        row[label] = key
        row["planned_case_count"] += 1
        execution = execution_by_case_id.get(case.case_id)
        if execution is None:
            row["pending_case_count"] += 1
            continue
        if execution.reused_from_report:
            row["reused_case_count"] += 1
        else:
            row["executed_case_count"] += 1
        duration_seconds = _safe_float(execution.duration_seconds)
        if duration_seconds is not None:
            row["execution_duration_seconds_total"] = round(
                float(row.get("execution_duration_seconds_total", 0.0)) + duration_seconds,
                6,
            )
        child_wall_time = _safe_float(execution.child_artifacts.get("child_wall_time_seconds"))
        if child_wall_time is not None:
            row["child_wall_time_seconds_total"] = round(
                float(row.get("child_wall_time_seconds_total", 0.0)) + child_wall_time,
                6,
            )
        if execution.status in {"ok", "skipped_existing_ok"}:
            row["successful_case_count"] += 1
        if execution.status == "failed":
            row["failed_case_count"] += 1

    for case in skipped_cases:
        key = extractor(case.site)
        row = groups[key]
        row[label] = key
        row["skipped_case_count"] += 1

    rows = list(groups.values())
    for row in rows:
        executed_count = int(row.get("executed_case_count", 0)) + int(
            row.get("reused_case_count", 0)
        )
        duration_total = _safe_float(row.get("execution_duration_seconds_total"))
        child_total = _safe_float(row.get("child_wall_time_seconds_total"))
        row["execution_duration_seconds_mean"] = (
            None
            if duration_total is None or executed_count <= 0
            else round(duration_total / executed_count, 6)
        )
        row["child_wall_time_seconds_mean"] = (
            None
            if child_total is None or executed_count <= 0
            else round(child_total / executed_count, 6)
        )
    rows.sort(key=lambda row: str(row[label]).lower())
    return rows


def _build_site_inventory_rows(
    *,
    selected_sites: Sequence[RegionalLabSiteRecord],
    planned_cases: Sequence[RegionalLabPlannedCase],
    skipped_cases: Sequence[RegionalLabSkippedCase],
    executions: Sequence[RegionalLabExecution],
) -> list[dict[str, Any]]:
    """Build one site inventory CSV."""
    execution_by_case_id = _execution_by_case_id(executions)
    rows: list[dict[str, Any]] = []
    for site in selected_sites:
        site_planned = [case for case in planned_cases if case.site.site_id == site.site_id]
        site_skipped = [case for case in skipped_cases if case.site.site_id == site.site_id]
        site_executions = [
            execution
            for case in site_planned
            if (execution := execution_by_case_id.get(case.case_id)) is not None
        ]
        row = site.to_inventory_mapping()
        row.update(
            {
                "planned_case_count": len(site_planned),
                "skipped_case_count": len(site_skipped),
                "executed_case_count": len(
                    [item for item in site_executions if not item.reused_from_report]
                ),
                "reused_case_count": len(
                    [item for item in site_executions if item.reused_from_report]
                ),
                "failed_case_count": len(
                    [item for item in site_executions if item.status == "failed"]
                ),
                "execution_duration_seconds_total": round(
                    sum(
                        float(item.duration_seconds)
                        for item in site_executions
                        if item.duration_seconds is not None
                    ),
                    6,
                )
                if site_executions
                else None,
                "recipes_planned": ";".join(case.recipe_id for case in site_planned),
                "recipes_skipped": ";".join(case.recipe_id for case in site_skipped),
            }
        )
        rows.append(row)
    rows.sort(key=lambda row: str(row["site_id"]).lower())
    return rows


def _build_case_rows(
    *,
    planned_cases: Sequence[RegionalLabPlannedCase],
    skipped_cases: Sequence[RegionalLabSkippedCase],
    executions: Sequence[RegionalLabExecution],
) -> list[dict[str, Any]]:
    """Build one case matrix CSV combining planned, skipped, and executed cases."""
    execution_by_case_id = _execution_by_case_id(executions)
    rows: list[dict[str, Any]] = []
    for case in planned_cases:
        execution = execution_by_case_id.get(case.case_id)
        row = case.to_summary_mapping()
        row["status"] = "planned" if execution is None else execution.status
        row["returncode"] = None if execution is None else execution.returncode
        row["duration_seconds"] = None if execution is None else execution.duration_seconds
        row["reused_from_report"] = False if execution is None else execution.reused_from_report
        row["child_artifacts_json"] = (
            "" if execution is None else json.dumps(execution.child_artifacts, ensure_ascii=True)
        )
        row["child_wall_time_seconds"] = (
            None
            if execution is None
            else _safe_float(execution.child_artifacts.get("child_wall_time_seconds"))
        )
        row["child_success"] = (
            None if execution is None else execution.child_artifacts.get("child_success")
        )
        row["reason"] = ""
        row["detail"] = ""
        rows.append(row)
    for skipped in skipped_cases:
        row = skipped.to_summary_mapping()
        row["status"] = f"skipped_{skipped.reason}"
        row["returncode"] = None
        row["duration_seconds"] = None
        row["reused_from_report"] = False
        row["child_artifacts_json"] = ""
        row["child_wall_time_seconds"] = None
        row["child_success"] = None
        rows.append(row)
    rows.sort(
        key=lambda row: (str(row.get("recipe_id", "")).lower(), str(row.get("site_id", "")).lower())
    )
    return rows


def _build_execution_metric_rows(
    *,
    executions: Sequence[RegionalLabExecution],
) -> list[dict[str, Any]]:
    """Build one flat per-execution CSV enriched with child artifacts."""
    rows: list[dict[str, Any]] = []
    for execution in executions:
        row = execution.case.to_summary_mapping()
        row.update(
            {
                "status": execution.status,
                "returncode": execution.returncode,
                "duration_seconds": execution.duration_seconds,
                "reused_from_report": execution.reused_from_report,
                "command_json": json.dumps(list(execution.command), ensure_ascii=True),
            }
        )
        row.update(execution.child_artifacts)
        rows.append(row)
    rows.sort(
        key=lambda row: (str(row.get("recipe_id", "")).lower(), str(row.get("site_id", "")).lower())
    )
    return rows


def _render_summary_markdown(
    *,
    cfg: RegionalLabConfig,
    selected_sites: Sequence[RegionalLabSiteRecord],
    planned_cases: Sequence[RegionalLabPlannedCase],
    skipped_cases: Sequence[RegionalLabSkippedCase],
    executions: Sequence[RegionalLabExecution],
    recipe_summary_rows: Sequence[Mapping[str, Any]],
    cluster_summary_rows: Sequence[Mapping[str, Any]],
    region_summary_rows: Sequence[Mapping[str, Any]],
) -> str:
    """Render one compact Markdown report for the regional lab."""
    executed_fresh = [item for item in executions if not item.reused_from_report]
    reused = [item for item in executions if item.reused_from_report]
    failed = [item for item in executions if item.status == "failed"]

    lines = [
        f"# Regional Lab Summary: {cfg.lab_id}",
        "",
        f"- Config: `{cfg.config_path}`",
        f"- Site catalog: `{cfg.catalog.path}`",
        f"- Selected sites: {len(selected_sites)}",
        f"- Planned cases: {len(planned_cases)}",
        f"- Skipped cases: {len(skipped_cases)}",
        f"- Executed cases: {len(executed_fresh)}",
        f"- Reused cases: {len(reused)}",
        f"- Failed cases: {len(failed)}",
        "",
        "## Recipes",
        "",
        "| Recipe | Candidate sites | Planned | Skipped | Executed | Reused | Failed | Pending |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in recipe_summary_rows:
        lines.append(
            "| {recipe_id} | {candidate_site_count} | {planned_case_count} | "
            "{skipped_case_count} | {executed_case_count} | {reused_case_count} | "
            "{failed_case_count} | {pending_case_count} |".format(**row)
        )

    lines.extend(
        [
            "",
            "## Clusters",
            "",
            "| Cluster | Sites | Planned | Skipped | Executed | Reused | Failed | Pending |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in cluster_summary_rows:
        lines.append(
            "| {cluster_id} | {site_count} | {planned_case_count} | "
            "{skipped_case_count} | {executed_case_count} | {reused_case_count} | "
            "{failed_case_count} | {pending_case_count} |".format(**row)
        )

    lines.extend(
        [
            "",
            "## Regions",
            "",
            "| Region | Sites | Planned | Skipped | Executed | Reused | Failed | Pending |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in region_summary_rows:
        lines.append(
            "| {region_id} | {site_count} | {planned_case_count} | "
            "{skipped_case_count} | {executed_case_count} | {reused_case_count} | "
            "{failed_case_count} | {pending_case_count} |".format(**row)
        )

    if skipped_cases:
        lines.extend(["", "## Coverage Gaps", ""])
        for skipped in skipped_cases:
            lines.append(
                f"- `{skipped.recipe_id}` / `{skipped.site.site_id}`: "
                f"{skipped.reason} ({skipped.detail})"
            )

    return "\n".join(lines) + "\n"


def _write_summary_artifacts(
    *,
    cfg: RegionalLabConfig,
    selected_sites: Sequence[RegionalLabSiteRecord],
    planned_cases: Sequence[RegionalLabPlannedCase],
    skipped_cases: Sequence[RegionalLabSkippedCase],
    executions: Sequence[RegionalLabExecution],
) -> dict[str, str]:
    """Persist compact synthesis artifacts for the current regional-lab state."""
    recipe_summary_rows = _build_recipe_summaries(
        cfg=cfg,
        selected_sites=selected_sites,
        planned_cases=planned_cases,
        skipped_cases=skipped_cases,
        executions=executions,
    )
    cluster_summary_rows = _build_group_summary(
        label="cluster_id",
        selected_sites=selected_sites,
        planned_cases=planned_cases,
        skipped_cases=skipped_cases,
        executions=executions,
        extractor=lambda site: site.cluster_id or "unassigned",
    )
    region_summary_rows = _build_group_summary(
        label="region_id",
        selected_sites=selected_sites,
        planned_cases=planned_cases,
        skipped_cases=skipped_cases,
        executions=executions,
        extractor=lambda site: site.region_id or "unassigned",
    )
    family_summary_rows = _build_group_summary(
        label="cluster_family",
        selected_sites=selected_sites,
        planned_cases=planned_cases,
        skipped_cases=skipped_cases,
        executions=executions,
        extractor=lambda site: site.cluster_family or "unassigned",
    )
    scale_summary_rows = _build_group_summary(
        label="cluster_scale",
        selected_sites=selected_sites,
        planned_cases=planned_cases,
        skipped_cases=skipped_cases,
        executions=executions,
        extractor=lambda site: site.cluster_scale or "unassigned",
    )
    site_inventory_rows = _build_site_inventory_rows(
        selected_sites=selected_sites,
        planned_cases=planned_cases,
        skipped_cases=skipped_cases,
        executions=executions,
    )
    case_rows = _build_case_rows(
        planned_cases=planned_cases,
        skipped_cases=skipped_cases,
        executions=executions,
    )
    execution_metric_rows = _build_execution_metric_rows(executions=executions)

    paths = {
        "site_inventory_csv": str((cfg.output_root / "regional_lab_site_inventory.csv").resolve()),
        "case_matrix_csv": str((cfg.output_root / "regional_lab_case_matrix.csv").resolve()),
        "execution_metrics_csv": str(
            (cfg.output_root / "regional_lab_execution_metrics.csv").resolve()
        ),
        "recipe_summary_csv": str((cfg.output_root / "regional_lab_recipe_summary.csv").resolve()),
        "cluster_summary_csv": str(
            (cfg.output_root / "regional_lab_cluster_summary.csv").resolve()
        ),
        "region_summary_csv": str((cfg.output_root / "regional_lab_region_summary.csv").resolve()),
        "family_summary_csv": str((cfg.output_root / "regional_lab_family_summary.csv").resolve()),
        "scale_summary_csv": str((cfg.output_root / "regional_lab_scale_summary.csv").resolve()),
        "summary_markdown": str((cfg.output_root / "regional_lab_summary.md").resolve()),
    }

    _write_csv_rows(
        Path(paths["site_inventory_csv"]),
        fieldnames=_collect_fieldnames(site_inventory_rows)
        if site_inventory_rows
        else [
            "site_id",
            "site_label",
            "cluster_id",
            "cluster_label",
            "cluster_family",
            "cluster_scale",
            "region_id",
            "source_selection_id",
            "site_status",
            "maturity",
            "enabled",
            "x",
            "y",
            "area_km2",
            "site_tags",
            "cluster_tags",
            "tags",
            "resolved_paths_json",
            "planned_case_count",
            "skipped_case_count",
            "executed_case_count",
            "reused_case_count",
            "failed_case_count",
            "recipes_planned",
            "recipes_skipped",
        ],
        rows=site_inventory_rows,
    )
    _write_csv_rows(
        Path(paths["case_matrix_csv"]),
        fieldnames=_collect_fieldnames(case_rows)
        if case_rows
        else [
            "case_id",
            "site_id",
            "recipe_id",
            "status",
        ],
        rows=case_rows,
    )
    _write_csv_rows(
        Path(paths["execution_metrics_csv"]),
        fieldnames=_collect_fieldnames(execution_metric_rows)
        if execution_metric_rows
        else ["case_id", "site_id", "recipe_id", "status"],
        rows=execution_metric_rows,
    )
    for key, rows in (
        ("recipe_summary_csv", recipe_summary_rows),
        ("cluster_summary_csv", cluster_summary_rows),
        ("region_summary_csv", region_summary_rows),
        ("family_summary_csv", family_summary_rows),
        ("scale_summary_csv", scale_summary_rows),
    ):
        fieldnames = _collect_fieldnames(rows) if rows else []
        if not fieldnames:
            continue
        _write_csv_rows(Path(paths[key]), fieldnames=fieldnames, rows=rows)

    Path(paths["summary_markdown"]).write_text(
        _render_summary_markdown(
            cfg=cfg,
            selected_sites=selected_sites,
            planned_cases=planned_cases,
            skipped_cases=skipped_cases,
            executions=executions,
            recipe_summary_rows=recipe_summary_rows,
            cluster_summary_rows=cluster_summary_rows,
            region_summary_rows=region_summary_rows,
        ),
        encoding="utf-8",
    )
    return paths


def _build_report_payload(
    *,
    cfg: RegionalLabConfig,
    selected_sites: list[RegionalLabSiteRecord],
    planned_cases: list[RegionalLabPlannedCase],
    skipped_cases: list[RegionalLabSkippedCase],
    executions: list[RegionalLabExecution],
    synthesis_paths: Mapping[str, str],
) -> dict[str, Any]:
    """Build one JSON-serializable execution report."""
    execution_by_case_id = _execution_by_case_id(executions)
    failed = [item for item in executions if item.status == "failed"]
    reused = [item for item in executions if item.reused_from_report]
    executed_fresh = [item for item in executions if not item.reused_from_report]
    pending_count = len(planned_cases) - len(executions)
    python_executable = cfg.python_executable or Path(sys.executable)

    cases_payload: list[dict[str, Any]] = []
    for case in planned_cases:
        execution = execution_by_case_id.get(case.case_id)
        command = build_run_command(case, python_executable=python_executable)
        payload = case.to_summary_mapping()
        payload["command"] = command
        if execution is None:
            payload["status"] = "planned"
            payload["returncode"] = None
            payload["duration_seconds"] = None
            payload["reused_from_report"] = False
        else:
            payload["status"] = execution.status
            payload["returncode"] = execution.returncode
            payload["duration_seconds"] = execution.duration_seconds
            payload["reused_from_report"] = execution.reused_from_report
            payload["child_artifacts"] = dict(execution.child_artifacts)
        if execution is None:
            payload["child_artifacts"] = {}
        cases_payload.append(payload)

    return {
        "schema_version": "regional_lab_report_v2",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "lab_id": cfg.lab_id,
        "config_path": str(cfg.config_path),
        "site_catalog_path": str(cfg.catalog.path),
        "output_root": str(cfg.output_root),
        "execute": bool(cfg.execute),
        "continue_on_error": bool(cfg.continue_on_error),
        "resume_from_report": bool(cfg.resume_from_report),
        "skip_completed_cases": bool(cfg.skip_completed_cases),
        "selected_site_count": len(selected_sites),
        "planned_case_count": len(planned_cases),
        "skipped_case_count": len(skipped_cases),
        "executed_case_count": len(executed_fresh),
        "reused_case_count": len(reused),
        "successful_case_count": len(
            [item for item in executions if item.status in {"ok", "skipped_existing_ok"}]
        ),
        "failed_case_count": len(failed),
        "pending_case_count": pending_count,
        "all_passed": len(failed) == 0 and pending_count == 0,
        "selected_sites": [site.to_summary_mapping() for site in selected_sites],
        "cases": cases_payload,
        "skipped_cases": [case.to_summary_mapping() for case in skipped_cases],
        "synthesis_paths": dict(synthesis_paths),
    }


def _load_previous_ok_case_ids(report_path: Path) -> set[str]:
    """Return case identifiers already marked as successful in one previous report."""
    if not report_path.is_file():
        return set()
    try:
        payload = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    cases = payload.get("cases", [])
    if not isinstance(cases, list):
        return set()
    out: set[str] = set()
    for case in cases:
        if not isinstance(case, Mapping):
            continue
        case_id = _normalize_text(case.get("case_id"))
        status = _normalize_text(case.get("status"))
        if case_id is None or status is None:
            continue
        if status.lower() in {"ok", "skipped_existing_ok"}:
            out.add(case_id)
    return out


class RegionalLabLauncher:
    """Expand one site catalog into a concrete regional-lab campaign."""

    def __init__(self, config_path: str | Path) -> None:
        self.cfg = RegionalLabConfig.from_file(config_path)

    def run(self) -> dict[str, Any]:
        """Build the plan, optionally execute it, and persist summary artifacts."""
        cfg = self.cfg
        cfg.output_root.mkdir(parents=True, exist_ok=True)
        sites = load_site_catalog(cfg.catalog)
        selected_sites, planned_cases, skipped_cases = build_regional_lab_plan(cfg, sites)

        plan_path = (cfg.output_root / "regional_lab_plan.json").resolve()
        report_path = (cfg.output_root / "regional_lab_report.json").resolve()
        _write_json(
            plan_path,
            _build_plan_payload(
                cfg=cfg,
                selected_sites=selected_sites,
                planned_cases=planned_cases,
                skipped_cases=skipped_cases,
            ),
        )

        previous_ok_case_ids = set()
        if cfg.resume_from_report and cfg.skip_completed_cases:
            previous_ok_case_ids = _load_previous_ok_case_ids(report_path)

        executions: list[RegionalLabExecution] = []
        synthesis_paths = _write_summary_artifacts(
            cfg=cfg,
            selected_sites=selected_sites,
            planned_cases=planned_cases,
            skipped_cases=skipped_cases,
            executions=executions,
        )
        _write_json(
            report_path,
            _build_report_payload(
                cfg=cfg,
                selected_sites=selected_sites,
                planned_cases=planned_cases,
                skipped_cases=skipped_cases,
                executions=executions,
                synthesis_paths=synthesis_paths,
            ),
        )

        if cfg.execute:
            python_executable = cfg.python_executable or Path(sys.executable)
            for case in planned_cases:
                command = build_run_command(case, python_executable=python_executable)
                if case.case_id in previous_ok_case_ids:
                    executions.append(
                        RegionalLabExecution(
                            case=case,
                            command=tuple(command),
                            status="skipped_existing_ok",
                            returncode=0,
                            duration_seconds=0.0,
                            reused_from_report=True,
                            child_artifacts=_extract_child_case_artifacts(case),
                        )
                    )
                else:
                    started_at = time.perf_counter()
                    completed = subprocess.run(command, cwd=REPO_ROOT, check=False)
                    executions.append(
                        RegionalLabExecution(
                            case=case,
                            command=tuple(command),
                            status="ok" if completed.returncode == 0 else "failed",
                            returncode=int(completed.returncode),
                            duration_seconds=round(float(time.perf_counter() - started_at), 6),
                            reused_from_report=False,
                            child_artifacts=_extract_child_case_artifacts(case),
                        )
                    )
                synthesis_paths = _write_summary_artifacts(
                    cfg=cfg,
                    selected_sites=selected_sites,
                    planned_cases=planned_cases,
                    skipped_cases=skipped_cases,
                    executions=executions,
                )
                _write_json(
                    report_path,
                    _build_report_payload(
                        cfg=cfg,
                        selected_sites=selected_sites,
                        planned_cases=planned_cases,
                        skipped_cases=skipped_cases,
                        executions=executions,
                        synthesis_paths=synthesis_paths,
                    ),
                )
                if executions[-1].status == "failed" and not cfg.continue_on_error:
                    break

        summary = {
            "lab_id": cfg.lab_id,
            "output_root": str(cfg.output_root),
            "selected_site_count": len(selected_sites),
            "planned_case_count": len(planned_cases),
            "skipped_case_count": len(skipped_cases),
            "executed_case_count": len(
                [item for item in executions if not item.reused_from_report]
            ),
            "reused_case_count": len([item for item in executions if item.reused_from_report]),
            "failed_case_count": len([item for item in executions if item.status == "failed"]),
            "plan_path": str(plan_path),
            "report_path": str(report_path),
            **synthesis_paths,
        }
        return summary
