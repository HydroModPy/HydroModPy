"""Shared contract helpers for site-selection manifest files."""

from __future__ import annotations

import csv
import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

SITE_SELECTION_MANIFEST_NAME = "site_selection_manifest.json"
MANIFEST_SCHEMA_VERSION = "site_selection_manifest_v1"
REQUIRED_MANIFEST_KEYS = (
    "schema_version",
    "created_at_utc",
    "selection_id",
    "action",
    "output_root",
    "strategy",
    "territory",
    "input",
    "criteria",
    "counts",
    "outputs",
)
REQUIRED_OUTPUT_KEYS = (
    "criteria_components_jsonl",
    "site_selection_decisions_jsonl",
    "site_selection_manifest_json",
)
REVIEW_DIR_NAME = "review"
REVIEW_HTML_NAME = "index.html"
REVIEW_MAP_PNG_NAME = "site_selection_map.png"


def write_selection_manifest(path: str | Path, manifest: dict[str, Any]) -> Path:
    """Write a site-selection manifest as stable JSON."""

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=True, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return destination


def load_selection_manifest(path: str | Path) -> dict[str, Any]:
    """Load a site-selection manifest."""

    return json.loads(Path(path).read_text(encoding="utf-8"))


def manifest_output_path(
    manifest: Mapping[str, Any],
    key: str,
    *,
    manifest_path: str | Path | None = None,
) -> Path | None:
    """Resolve one output path from a manifest, or return ``None`` when absent."""

    outputs = manifest.get("outputs")
    if not isinstance(outputs, Mapping):
        return None
    value = outputs.get(key)
    if not value:
        return None
    output_root = manifest_output_root(manifest, manifest_path=manifest_path)
    return resolve_manifest_output_path(str(value), output_root=output_root)


def manifest_output_root(
    manifest: Mapping[str, Any],
    *,
    manifest_path: str | Path | None,
) -> Path:
    """Resolve the manifest output root, falling back to the manifest directory."""

    raw_root = manifest.get("output_root")
    if raw_root:
        root = Path(str(raw_root)).expanduser()
        if root.is_absolute():
            return root.resolve()
    if manifest_path is not None:
        base = Path(manifest_path).expanduser().resolve().parent
        if raw_root:
            return (base / str(raw_root)).resolve()
        return base
    if raw_root:
        return Path(str(raw_root)).expanduser().resolve()
    return Path.cwd().resolve()


def resolve_manifest_output_path(value: str, *, output_root: Path) -> Path:
    """Resolve a manifest output entry against its output root."""

    path = Path(value).expanduser()
    if path.is_absolute():
        return path.resolve()
    return (output_root / path).resolve()


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
    output_root = manifest_output_root(manifest, manifest_path=manifest_path)
    for key, value in sorted(outputs.items()):
        if key in skip or not value:
            continue
        artifact_path = resolve_manifest_output_path(str(value), output_root=output_root)
        if not artifact_path.is_file():
            errors.append(f"missing output artifact for {key}: {artifact_path}")
            continue
        errors.extend(_validate_output_artifact(key, artifact_path))
    errors.extend(_validate_map_context_layers(manifest, output_root=output_root))
    return errors


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
        layer_path = resolve_manifest_output_path(str(raw_path), output_root=output_root)
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
    "REVIEW_DIR_NAME",
    "REVIEW_HTML_NAME",
    "REVIEW_MAP_PNG_NAME",
    "SITE_SELECTION_MANIFEST_NAME",
    "load_selection_manifest",
    "manifest_output_path",
    "manifest_output_root",
    "resolve_manifest_output_path",
    "validate_selection_manifest",
    "validate_selection_manifest_data",
    "write_selection_manifest",
]
