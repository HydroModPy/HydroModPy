"""Runtime data carriers for the regional-lab launcher family."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hydromodpy.analysis.batch.config import RegionalLabRecipeConfig


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
