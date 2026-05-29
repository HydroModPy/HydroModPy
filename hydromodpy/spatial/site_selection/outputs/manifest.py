"""Manifest helpers for site-selection runs."""

from __future__ import annotations

import csv
import json
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hydromodpy.schema.site_selection_manifest import (
    MANIFEST_SCHEMA_VERSION,
    REQUIRED_MANIFEST_KEYS,
    REQUIRED_OUTPUT_KEYS,
    SITE_SELECTION_MANIFEST_NAME,
    load_selection_manifest,
    manifest_output_path,
    write_selection_manifest,
)
from hydromodpy.schema.site_selection_manifest import (
    manifest_output_root as _manifest_output_root,
)
from hydromodpy.schema.site_selection_manifest import (
    resolve_manifest_output_path as _resolve_manifest_output_path,
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


def validate_selection_manifest(
    path: str | Path,
    *,
    check_outputs: bool = True,
    skip_output_keys: Iterable[str] = ("site_selection_report_html",),
) -> list[str]:
    """Return validation errors for a completed site-selection manifest.

    The manifest is the stable contract between the selection workflow, review
    tooling and downstream loaders. Validation therefore checks both the basic
    schema shape and, by default, the existence of files explicitly referenced
    in ``outputs``. The HTML report is skipped by default because it may be the
    artifact currently being generated from the manifest.
    """

    manifest_file = Path(path).expanduser().resolve()
    try:
        manifest = load_selection_manifest(manifest_file)
    except (json.JSONDecodeError, OSError) as exc:
        return [f"cannot read manifest: {exc}"]
    return validate_selection_manifest_data(
        manifest,
        manifest_path=manifest_file,
        check_outputs=check_outputs,
        skip_output_keys=skip_output_keys,
    )


def validate_selection_manifest_data(
    manifest: Mapping[str, Any],
    *,
    manifest_path: str | Path | None = None,
    check_outputs: bool = True,
    skip_output_keys: Iterable[str] = ("site_selection_report_html",),
) -> list[str]:
    """Return validation errors for an in-memory manifest mapping."""

    errors: list[str] = []
    for key in REQUIRED_MANIFEST_KEYS:
        if key not in manifest:
            errors.append(f"missing top-level key: {key}")

    schema_version = manifest.get("schema_version")
    if schema_version != MANIFEST_SCHEMA_VERSION:
        errors.append(
            f"unsupported schema_version: {schema_version!r}; expected {MANIFEST_SCHEMA_VERSION!r}"
        )

    outputs = manifest.get("outputs")
    if not isinstance(outputs, Mapping):
        errors.append("outputs must be a mapping")
        return errors

    for key in REQUIRED_OUTPUT_KEYS:
        if key not in outputs:
            errors.append(f"missing required output: {key}")

    if not check_outputs:
        return errors

    skip = set(skip_output_keys)
    output_root = _manifest_output_root(manifest, manifest_path=manifest_path)
    for key, value in sorted(outputs.items()):
        if key in skip or not value:
            continue
        artifact_path = _resolve_manifest_output_path(str(value), output_root=output_root)
        if not artifact_path.is_file():
            errors.append(f"missing output artifact for {key}: {artifact_path}")
            continue
        errors.extend(_validate_output_artifact(key, artifact_path))
    errors.extend(_validate_map_context_layers(manifest, output_root=output_root))
    return errors


def _relative_path(path: str | Path, *, root: Path) -> str:
    resolved = Path(path).expanduser().resolve()
    try:
        return resolved.relative_to(root).as_posix()
    except ValueError:
        return str(resolved)


def _path_or_none(path: Path | None) -> str | None:
    return None if path is None else str(path)


def _validate_output_artifact(key: str, path: Path) -> list[str]:
    if key.endswith("_geojson"):
        return _validate_geojson_artifact(key, path)
    if key.endswith("_geoparquet"):
        return _validate_geoparquet_artifact(key, path)
    if key.endswith("_gpkg"):
        return _validate_gpkg_artifact(key, path)
    if key.endswith("_jsonl"):
        return _validate_jsonl_artifact(key, path)
    if key.endswith("_csv"):
        return _validate_csv_artifact(key, path)
    if key.endswith("_png"):
        return _validate_png_artifact(key, path)
    if key.endswith("_json"):
        return _validate_json_artifact(key, path)
    return []


def _validate_map_context_layers(
    manifest: Mapping[str, Any],
    *,
    output_root: Path,
) -> list[str]:
    errors: list[str] = []
    context = manifest.get("map_context")
    if not isinstance(context, Mapping):
        return errors
    layers = context.get("layers")
    if layers is None:
        return errors
    if not isinstance(layers, list):
        return ["map_context.layers must be a list"]
    for index, layer in enumerate(layers):
        if not isinstance(layer, Mapping):
            errors.append(f"map_context.layers[{index}] must be an object")
            continue
        raw_path = layer.get("path")
        if not raw_path:
            errors.append(f"map_context.layers[{index}] missing path")
            continue
        layer_path = _resolve_manifest_output_path(str(raw_path), output_root=output_root)
        if not layer_path.is_file():
            errors.append(f"missing map context layer {index}: {layer_path}")
            continue
        errors.extend(_validate_geojson_artifact(f"map_context.layers[{index}]", layer_path))
    return errors


def _validate_geojson_artifact(key: str, path: Path) -> list[str]:
    errors: list[str] = []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return [f"invalid GeoJSON for {key}: {exc}"]
    if not isinstance(payload, Mapping):
        return [f"invalid GeoJSON for {key}: root must be an object"]
    if payload.get("type") != "FeatureCollection":
        errors.append(f"invalid GeoJSON for {key}: type must be FeatureCollection")
    features = payload.get("features")
    if not isinstance(features, list):
        errors.append(f"invalid GeoJSON for {key}: features must be a list")
        return errors
    crs = str(payload.get("hydromodpy_coordinate_crs") or "")
    if features and not crs:
        errors.append(f"invalid GeoJSON for {key}: missing hydromodpy_coordinate_crs")
    for index, feature in enumerate(features):
        if not isinstance(feature, Mapping):
            errors.append(f"invalid GeoJSON for {key}: feature {index} must be an object")
            continue
        if feature.get("type") != "Feature":
            errors.append(f"invalid GeoJSON for {key}: feature {index} type must be Feature")
        geometry = feature.get("geometry")
        if not isinstance(geometry, Mapping):
            errors.append(f"invalid GeoJSON for {key}: feature {index} missing geometry")
            continue
        if not geometry.get("type"):
            errors.append(f"invalid GeoJSON for {key}: feature {index} geometry missing type")
        if "coordinates" not in geometry:
            errors.append(
                f"invalid GeoJSON for {key}: feature {index} geometry missing coordinates"
            )
    return errors


def _validate_jsonl_artifact(key: str, path: Path) -> list[str]:
    errors: list[str] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        return [f"invalid JSONL for {key}: {exc}"]
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"invalid JSONL for {key} at line {line_number}: {exc}")
    return errors


def _validate_csv_artifact(key: str, path: Path) -> list[str]:
    try:
        with path.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.reader(handle)
            header = next(reader, None)
    except OSError as exc:
        return [f"invalid CSV for {key}: {exc}"]
    if not header:
        return [f"invalid CSV for {key}: missing header"]
    return []


def _validate_png_artifact(key: str, path: Path) -> list[str]:
    try:
        size = path.stat().st_size
        with path.open("rb") as handle:
            signature = handle.read(8)
    except OSError as exc:
        return [f"invalid PNG for {key}: {exc}"]
    if size < 100:
        return [f"invalid PNG for {key}: file is too small ({size} bytes)"]
    if signature != b"\x89PNG\r\n\x1a\n":
        return [f"invalid PNG for {key}: bad PNG signature"]
    return []


def _validate_json_artifact(key: str, path: Path) -> list[str]:
    try:
        json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return [f"invalid JSON for {key}: {exc}"]
    return []


def _validate_geoparquet_artifact(key: str, path: Path) -> list[str]:
    try:
        from hydromodpy.core.io.geoparquet import read_geoparquet

        frame = read_geoparquet(path)
    except Exception as exc:  # noqa: BLE001 - manifest validation reports artifact errors.
        return [f"invalid GeoParquet for {key}: {exc}"]
    errors = _validate_geodataframe(key, frame)
    if frame.crs is None:
        errors.append(f"invalid GeoParquet for {key}: missing CRS")
    return errors


def _validate_gpkg_artifact(key: str, path: Path) -> list[str]:
    try:
        import geopandas as gpd
    except ImportError as exc:
        return [f"cannot validate GeoPackage for {key}: {exc}"]
    try:
        layers = gpd.list_layers(path) if hasattr(gpd, "list_layers") else None
    except Exception:
        layers = None
    try:
        if layers is not None and len(layers) > 0:
            layer_name = str(layers.iloc[0]["name"] if hasattr(layers, "iloc") else layers[0])
            frame = gpd.read_file(path, layer=layer_name)
        else:
            frame = gpd.read_file(path)
    except Exception as exc:  # noqa: BLE001 - manifest validation reports artifact errors.
        return [f"invalid GeoPackage for {key}: {exc}"]
    return _validate_geodataframe(key, frame)


def _validate_geodataframe(key: str, frame: object) -> list[str]:
    errors: list[str] = []
    if not hasattr(frame, "geometry"):
        return [f"invalid vector artifact for {key}: missing geometry column"]
    if frame.empty:
        errors.append(f"invalid vector artifact for {key}: empty layer")
        return errors
    if frame.geometry.isna().all():
        errors.append(f"invalid vector artifact for {key}: all geometries are null")
    return errors


__all__ = [
    "MANIFEST_SCHEMA_VERSION",
    "REQUIRED_MANIFEST_KEYS",
    "REQUIRED_OUTPUT_KEYS",
    "SITE_SELECTION_MANIFEST_NAME",
    "build_selection_manifest",
    "load_selection_manifest",
    "manifest_output_path",
    "validate_selection_manifest",
    "validate_selection_manifest_data",
    "write_selection_manifest",
]
