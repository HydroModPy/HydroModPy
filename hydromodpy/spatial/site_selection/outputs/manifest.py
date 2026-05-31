"""Manifest helpers for site-selection runs."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hydromodpy.schema.site_selection_manifest import (
    MANIFEST_SCHEMA_VERSION,
)
from hydromodpy.spatial.site_selection.config import SiteSelectionConfig
from hydromodpy.spatial.site_selection.evaluation.selection import SelectionResult


def build_selection_manifest(
    *,
    config: SiteSelectionConfig,
    result: SelectionResult,
    output_paths: dict[str, Path],
    action: str,
    input_paths: dict[str, str | Path | None] | None = None,
    flow_products: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the official manifest for one completed site-selection run."""

    root = config.output_root.expanduser().resolve()
    decisions = list(result.decisions)
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "selection_id": config.selection_id,
        "action": action,
        "output_root": str(root),
        "strategy": {
            "principle": config.strategy.principle,
            "profile": config.strategy.profile,
            "effective_profile": config.effective_profile,
            "primary_axes": list(config.strategy.primary_axes),
            "primary_observation_type": config.strategy.primary_observation_type,
            "candidate_mode": config.strategy.candidate_mode or config.outlets.candidate_mode,
        },
        "territory": {
            "mode": config.territory.mode,
            "country": config.territory.country,
            "regions": list(config.territory.regions),
            "departments": list(config.territory.departments),
            "bbox": config.territory.bbox,
            "polygon_file": _path_or_none(config.territory.polygon_file),
        },
        "input": {
            "mode": config.input.mode,
            "catchments_csv": _path_or_none(config.input.catchments_csv),
            "region_id": config.input.region_id,
            "workspace_root": _path_or_none(config.input.workspace_root),
            "data_root": _path_or_none(config.input.data_root),
            "delineate_from_outlets": config.input.delineate_from_outlets,
            "paths": {
                key: _path_or_none(Path(value) if value is not None else None)
                for key, value in (input_paths or {}).items()
            },
        },
        "dem": {
            "source": config.dem.source,
            "path": _path_or_none(config.dem.path),
            "resolution_m": config.dem.resolution_m,
            "cache_policy": config.dem.cache_policy,
            "margin_km": config.dem.margin_km,
            "request_extent": config.dem.request_extent,
            "map_background_extent": config.dem.map_background_extent,
            "force_refresh": config.dem.force_refresh,
        },
        "outlets": {
            "candidate_mode": config.outlets.candidate_mode,
            "snap_strategy": config.outlets.snap_strategy,
            "snap_dist_m": config.outlets.snap_dist_m,
            "max_generated_candidates": config.outlets.max_generated_candidates,
            "max_rejected_candidate_audit_records": (
                config.outlets.max_rejected_candidate_audit_records
            ),
            "max_generated_network_cells": config.outlets.max_generated_network_cells,
            "reference_network_source": config.outlets.reference_network_source,
            "reference_network_path": _path_or_none(config.outlets.reference_network_path),
            "reference_network_max_distance_m": config.outlets.reference_network_max_distance_m,
            "reference_network_fetch_margin_m": config.outlets.reference_network_fetch_margin_m,
        },
        "criteria": {
            "ruleset": config.criteria.ruleset,
            "hard_reject": list(config.criteria.hard_reject),
            "warning": list(config.criteria.warning),
            "soft_score": list(config.criteria.soft_score),
            "report_only": list(config.criteria.report_only),
            "area": config.criteria.area.model_dump(mode="json"),
            "observations": config.criteria.observations.model_dump(mode="json"),
            "influence": config.criteria.influence.model_dump(mode="json"),
            "geology": config.criteria.geology.model_dump(mode="json"),
        },
        "counts": {
            "selected": len(result.selected),
            "rejected": len(result.rejected),
            "decisions": len(result.decisions),
            "criteria_components": len(result.criteria_components),
            "warnings": sum(1 for decision in decisions if decision.warning_flags),
            "blocking_rejections": sum(
                1 for decision in decisions if (not decision.selected and decision.blocking_flags)
            ),
        },
        "outputs": {
            key: _relative_path(path, root=root) for key, path in sorted(output_paths.items())
        },
        "map_context": {
            "layers": [
                {
                    "name": layer.name,
                    "path": _relative_path(layer.path, root=root),
                    "role": layer.role,
                    "label_field": layer.label_field,
                }
                for layer in config.map_context.layers
            ],
        },
        "flow_products": flow_products or {},
    }


def _relative_path(path: str | Path, *, root: Path) -> str:
    resolved = Path(path).expanduser().resolve()
    try:
        return resolved.relative_to(root).as_posix()
    except ValueError:
        return str(resolved)


def _path_or_none(path: Path | None) -> str | None:
    return None if path is None else str(path)


__all__ = ["build_selection_manifest"]
