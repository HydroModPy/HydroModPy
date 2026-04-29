"""Export self-contained catchment mesh bundles for external reuse.

The bundle format is intentionally plain:

- one copied planar `.msh` file,
- CSV tables for nodes, cells, edges, and geology fractions,
- one JSON metadata file describing conventions and optional payloads.

That keeps the export easy to inspect manually and easy to reuse from small
external scripts that do not want to import the full HydroModPy stack.
"""

from __future__ import annotations

import csv
import json
import shutil
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np
from shapely.geometry import LineString, Point
from shapely.ops import unary_union

from hydromodpy.core.units.hydraulic_conductivity import parse_to_m_per_s
from hydromodpy.spatial._protocols import get_geology_data_source
from hydromodpy.spatial.domain.depth_model_config import (
    ConstantThicknessDepthModel,
    FlatSubstratumDepthModel,
)
from hydromodpy.spatial.domain.domain import Domain
from hydromodpy.spatial.field.geology.geology_field import GeologyField
from hydromodpy.spatial.mesh.gmsh_grid._bundle_export_contracts import (
    CatchmentBundleGeologyExportConfig,
    CatchmentBundleHydraulicPropertiesConfig,
    CatchmentBundleHydraulicPropertyConfig,
    CatchmentBundleMetadata,
    CatchmentBundleSummaryReference,
    GeologyFractionRow,
    GeologyProjectionPayload,
    HydraulicPropertiesPayload,
    HydraulicPropertyPayload,
)
from hydromodpy.spatial.mesh.gmsh_grid._river_linework_matching import (
    RiverLineworkMatcher,
)
from hydromodpy.spatial.mesh.gmsh_grid.catchment_mesh_bundle_reader import (
    CatchmentMeshBundle,
    CatchmentMeshBundleCell,
    CatchmentMeshBundleEdge,
    CatchmentMeshBundleGeologyFraction,
    CatchmentMeshBundleNode,
    load_catchment_mesh_bundle,
)
from hydromodpy.spatial.mesh.gmsh_grid.exchange_api import load_planar_mesh
from hydromodpy.spatial.surface_sampling import PreparedSurfaceSampler

BUNDLE_SCHEMA_VERSION = "mesh_catchment_bundle_v1"
_NODATA_SENTINEL = ""


def resolve_default_catchment_mesh_bundle_dir(mesh_path: str | Path) -> Path:
    """Return the default sibling directory used for one exported bundle."""
    mesh_path_obj = Path(mesh_path).resolve()
    return mesh_path_obj.parent / f"{mesh_path_obj.stem}_bundle"


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
    """Write one UTF-8 CSV table used by the exchange bundle."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _normalize_optional_float(value: float | None) -> str | float:
    """Serialize optional floats using the bundle missing-value convention."""
    return _NODATA_SENTINEL if value is None or not np.isfinite(float(value)) else float(value)


def _normalize_optional_int(value: int | None) -> str | int:
    """Serialize optional integers using the bundle missing-value convention."""
    return _NODATA_SENTINEL if value is None else int(value)


def _resolve_config_relative_path(
    raw_path: str | Path,
    *,
    config_path: str | Path | None,
) -> Path:
    """Resolve one possibly config-relative path to an absolute filesystem path."""
    path = Path(str(raw_path)).expanduser()
    if path.is_absolute():
        return path.resolve()
    if config_path is None:
        return path.resolve()
    base_path = Path(config_path).resolve()
    base_dir = base_path.parent if base_path.suffix != "" else base_path
    return (base_dir / path).resolve()


def _load_zone_value_mapping_csv(
    csv_path: str | Path,
    *,
    key_column: str = "zone_key",
    value_column: str = "value",
) -> dict[str, float]:
    """Load one zone-key to numeric-value mapping from CSV."""
    key_col = str(key_column).strip()
    val_col = str(value_column).strip()
    if key_col == "" or val_col == "":
        raise ValueError("CSV key/value column names cannot be empty.")

    path = Path(csv_path)
    if not path.exists():
        raise FileNotFoundError(f"CSV values file not found: {path}")

    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        headers = [str(header).strip() for header in (reader.fieldnames or [])]
        if key_col not in headers:
            raise KeyError(
                f"CSV values file '{path}' is missing key column '{key_col}'. "
                f"Available columns: {headers}"
            )
        if val_col not in headers:
            raise KeyError(
                f"CSV values file '{path}' is missing value column '{val_col}'. "
                f"Available columns: {headers}"
            )

        values: dict[str, float] = {}
        for line_number, row in enumerate(reader, start=2):
            key = get_geology_data_source().normalize_zone_key(row.get(key_col, ""))
            if key == "":
                continue
            if key in values:
                raise ValueError(
                    f"Duplicate key '{key}' in CSV mapping '{path}' at line {line_number}."
                )
            raw_value = row.get(val_col, "")
            try:
                values[key] = float(raw_value)
            except Exception as exc:
                raise ValueError(
                    f"Invalid numeric value in CSV mapping '{path}' line {line_number}: "
                    f"column '{val_col}' -> {raw_value!r}"
                ) from exc

    if len(values) == 0:
        raise ValueError(f"CSV values file '{path}' does not define any key/value pair.")
    return values


def _parse_storage_coefficient_value(
    raw_value: object,
    *,
    label: str,
) -> float:
    if isinstance(raw_value, bool):
        raise TypeError(f"{label} must be numeric.")
    try:
        return float(raw_value)
    except Exception as exc:
        raise ValueError(f"{label} must be numeric, got {raw_value!r}.") from exc


def _normalize_property_mapping_values(
    raw_values: Mapping[str, object],
    *,
    value_parser,
    label_prefix: str,
) -> dict[str, float]:
    """Normalize one inline or CSV-derived mapping keyed by geology zone."""
    out: dict[str, float] = {}
    for raw_key, raw_value in dict(raw_values).items():
        key = get_geology_data_source().normalize_zone_key(raw_key)
        if key == "":
            raise ValueError(f"{label_prefix} contains one empty geology key.")
        if key in out:
            raise ValueError(
                f"{label_prefix} contains duplicate geology key '{key}' after normalization."
            )
        out[key] = float(value_parser(raw_value, label=f"{label_prefix}[{key!r}]"))
    return out


def _resolve_hydraulic_property_mapping(
    property_cfg: CatchmentBundleHydraulicPropertyConfig | None,
    *,
    property_name: str,
    config_path: str | Path | None,
    value_parser,
) -> HydraulicPropertyPayload:
    """Resolve one optional hydraulic property mapping section.

    The returned payload is summary-oriented: it carries parsed values together
    with provenance information useful in `metadata.json`.
    """
    if property_cfg is None:
        return HydraulicPropertyPayload(
            property_name=property_name,
            available=False,
        )

    values_source = str(property_cfg.values_source).strip().lower()
    if values_source == "csv":
        values_csv_path = _resolve_config_relative_path(
            str(property_cfg.values_csv_file),
            config_path=config_path,
        )
        raw_values = _load_zone_value_mapping_csv(
            values_csv_path,
            key_column=str(property_cfg.csv_key_column),
            value_column=str(property_cfg.csv_value_column),
        )
    else:
        values_csv_path = None
        raw_values = dict(property_cfg.values)

    values_by_zone_key = _normalize_property_mapping_values(
        raw_values,
        value_parser=value_parser,
        label_prefix=f"{property_name}.values",
    )
    raw_default_value = property_cfg.default_value
    default_value = (
        None
        if raw_default_value is None
        else float(value_parser(raw_default_value, label=f"{property_name}.default_value"))
    )
    return HydraulicPropertyPayload(
        property_name=property_name,
        available=bool(values_by_zone_key) or default_value is not None,
        values_by_zone_key=values_by_zone_key,
        default_value=default_value,
        values_source=values_source,
        values_csv_file=None if values_csv_path is None else str(values_csv_path),
        zone_keys_defined=tuple(sorted(values_by_zone_key)),
    )


def _build_fractions_by_cell(
    fraction_rows: tuple[GeologyFractionRow, ...],
) -> dict[int, list[tuple[str, float]]]:
    """Group geology-fraction rows by exported cell id."""
    out: dict[int, list[tuple[str, float]]] = {}
    for row in fraction_rows:
        cell_id = int(row.cell_id)
        zone_key = get_geology_data_source().normalize_zone_key(row.geology_key)
        fraction = float(row.fraction)
        if zone_key == "" or fraction <= 0.0:
            continue
        out.setdefault(cell_id, []).append((zone_key, fraction))
    return out


def _compute_weighted_cell_property_values(
    *,
    n_cells: int,
    cell_zone_keys: tuple[str, ...],
    fraction_rows: tuple[GeologyFractionRow, ...],
    property_payload: HydraulicPropertyPayload,
) -> tuple[tuple[float | None, ...], list[str]]:
    """Average per-zone property values onto cells using geology fractions."""
    if not property_payload.available:
        return tuple(None for _ in range(int(n_cells))), []

    values_by_zone_key = {
        get_geology_data_source().normalize_zone_key(key): float(value)
        for key, value in dict(property_payload.values_by_zone_key).items()
    }
    default_value = property_payload.default_value
    default_float = None if default_value is None else float(default_value)
    fractions_by_cell = _build_fractions_by_cell(fraction_rows)
    missing_zone_keys: set[str] = set()
    cell_values: list[float | None] = []

    for cell_idx in range(int(n_cells)):
        fractions = fractions_by_cell.get(int(cell_idx))
        if not fractions:
            dominant_key = (
                ""
                if cell_idx >= len(cell_zone_keys)
                else get_geology_data_source().normalize_zone_key(cell_zone_keys[cell_idx])
            )
            fractions = [] if dominant_key == "" else [(dominant_key, 1.0)]

        if not fractions:
            cell_values.append(None)
            continue

        weighted_sum = 0.0
        total_fraction = 0.0
        unresolved = False
        for zone_key, fraction in fractions:
            value = values_by_zone_key.get(zone_key, default_float)
            if value is None:
                missing_zone_keys.add(zone_key)
                unresolved = True
                break
            weighted_sum += float(fraction) * float(value)
            total_fraction += float(fraction)
        if unresolved or total_fraction <= 0.0:
            cell_values.append(None)
            continue
        cell_values.append(weighted_sum / total_fraction)

    return tuple(cell_values), sorted(missing_zone_keys)


def _build_hydraulic_properties_payload(
    *,
    mesh,
    geology_payload: GeologyProjectionPayload,
    hydraulic_properties_cfg: CatchmentBundleHydraulicPropertiesConfig | None,
    config_path: str | Path | None,
) -> HydraulicPropertiesPayload:
    """Build conductivity/storage payloads summarized at the cell scale."""
    conductivity_cfg = (
        None if hydraulic_properties_cfg is None else hydraulic_properties_cfg.conductivity
    )
    storage_cfg = (
        None if hydraulic_properties_cfg is None else hydraulic_properties_cfg.storage_coefficient
    )

    conductivity_unit = "m/s"
    if conductivity_cfg is not None and conductivity_cfg.unit is not None:
        conductivity_unit = str(conductivity_cfg.unit).strip() or "m/s"

    conductivity = _resolve_hydraulic_property_mapping(
        conductivity_cfg,
        property_name="conductivity",
        config_path=config_path,
        value_parser=lambda raw, label: parse_to_m_per_s(
            raw,
            location=label,
            default_unit=conductivity_unit,
        )[0],
    )
    storage = _resolve_hydraulic_property_mapping(
        storage_cfg,
        property_name="storage_coefficient",
        config_path=config_path,
        value_parser=_parse_storage_coefficient_value,
    )

    cell_zone_keys = tuple(str(v) for v in geology_payload.cell_zone_keys)
    fraction_rows = tuple(geology_payload.fraction_rows)
    conductivity_values, conductivity_missing = _compute_weighted_cell_property_values(
        n_cells=int(mesh.n_cells),
        cell_zone_keys=cell_zone_keys,
        fraction_rows=fraction_rows,
        property_payload=conductivity,
    )
    storage_values, storage_missing = _compute_weighted_cell_property_values(
        n_cells=int(mesh.n_cells),
        cell_zone_keys=cell_zone_keys,
        fraction_rows=fraction_rows,
        property_payload=storage,
    )

    conductivity_payload = replace(
        conductivity,
        output_field="hydraulic_conductivity_m_s",
        unit="m/s",
        cell_values=conductivity_values,
        missing_zone_keys=tuple(conductivity_missing),
    )
    storage_payload = replace(
        storage,
        output_field="storage_coefficient",
        unit="-",
        cell_values=storage_values,
        missing_zone_keys=tuple(storage_missing),
    )
    return HydraulicPropertiesPayload(
        available=bool(conductivity.available or storage.available),
        averaging="weighted_by_geology_fraction",
        conductivity=conductivity_payload,
        storage_coefficient=storage_payload,
    )


def _iter_line_geometries(lines_attr: object | None) -> list[object]:
    """Flatten a `river_trace.lines`-like payload into individual line geometries."""
    if lines_attr is None:
        return []
    out: list[object] = []
    for geometry in tuple(lines_attr):
        if geometry is None or bool(getattr(geometry, "is_empty", True)):
            continue
        geom_type = str(getattr(geometry, "geom_type", ""))
        if geom_type == "LineString":
            out.append(geometry)
            continue
        if geom_type == "MultiLineString":
            out.extend(
                line
                for line in getattr(geometry, "geoms", ())
                if not bool(getattr(line, "is_empty", True))
            )
    return out


def _surface_values_and_support(surface) -> tuple[np.ndarray, object | None]:
    """Extract the raw values array and raster support from one prepared surface."""
    sampler = PreparedSurfaceSampler.from_surface(surface)
    return sampler.values, sampler.support


def _sample_surface(surface, x_values, y_values) -> np.ndarray:
    """Sample one surface-like object without keeping one persistent sampler."""
    return PreparedSurfaceSampler.from_surface(surface).sample(x_values, y_values)


def _build_domain_for_bundle(*, surface, domain_cfg: object | None) -> Domain:
    """Resolve topography/substratum surfaces used by bundle export."""
    if surface is None:
        raise ValueError("domain_geographic.surface_topo is required for bundle export")
    domain = Domain(config=domain_cfg, surface_topo=surface)
    if domain.substratum is None:
        raise ValueError(
            "domain.depth_model did not produce a substratum surface for bundle export"
        )
    return domain


def _serialize_depth_model(domain: Domain) -> dict[str, Any]:
    """Return a compact metadata payload describing the active depth model."""
    depth_model = domain.config.depth_model
    if isinstance(depth_model, ConstantThicknessDepthModel):
        return {
            "type": str(depth_model.type),
            "thickness_m": float(depth_model.thickness),
        }
    if isinstance(depth_model, FlatSubstratumDepthModel):
        return {
            "type": str(depth_model.type),
            "substratum_elevation_m": float(depth_model.substratum_elevation),
        }
    return {"type": str(getattr(depth_model, "type", "unknown"))}


def _polygon_area(vertices: np.ndarray) -> float:
    """Compute the area of one planar cell polygon from its ordered vertices."""
    coords = np.asarray(vertices, dtype=float)
    x_vals = coords[:, 0]
    y_vals = coords[:, 1]
    return float(
        0.5 * abs(np.dot(x_vals, np.roll(y_vals, -1)) - np.dot(y_vals, np.roll(x_vals, -1)))
    )


def _resolve_geology_config_paths(
    geology_cfg: CatchmentBundleGeologyExportConfig,
    *,
    config_path: str | Path | None,
) -> dict[str, Any]:
    """Resolve geology paths relative to the calling config when needed.

    The export layer keeps a small typed contract, then converts it to the
    legacy loader mapping only at the edge where the geology loader still
    expects dictionary payloads.
    """

    cfg: dict[str, Any] = {
        "id": geology_cfg.field_id or "field_geology",
        "source": {
            "path": geology_cfg.source.path,
            "kind": geology_cfg.source.kind,
        },
        "cell_samples_per_axis": int(geology_cfg.cell_samples_per_axis),
    }
    source_cfg = dict(cfg["source"])
    if geology_cfg.source.code_field is not None:
        source_cfg["code_field"] = geology_cfg.source.code_field
    if geology_cfg.source.reference_raster_path is not None:
        source_cfg["reference_raster_path"] = geology_cfg.source.reference_raster_path
    source_cfg["path"] = get_geology_data_source().resolve_data_path(
        str(source_cfg["path"]),
        config_path=config_path,
    )
    reference_raster_path = source_cfg.get("reference_raster_path")
    if reference_raster_path is not None:
        source_cfg["reference_raster_path"] = get_geology_data_source().resolve_data_path(
            str(reference_raster_path),
            config_path=config_path,
        )
    cfg["source"] = source_cfg

    clip_polygon_path = cfg.get("clip_polygon_path")
    if clip_polygon_path:
        cfg["clip_polygon_path"] = get_geology_data_source().resolve_data_path(
            str(clip_polygon_path),
            config_path=config_path,
        )

    landsea_cfg = dict(cfg.get("landsea", {}))
    landsea_path = landsea_cfg.get("path")
    if landsea_path:
        landsea_cfg["path"] = get_geology_data_source().resolve_data_path(
            str(landsea_path),
            config_path=config_path,
        )
        cfg["landsea"] = landsea_cfg
    return cfg


def _compute_geology_payload(
    *,
    mesh,
    raster_support,
    geology_cfg: CatchmentBundleGeologyExportConfig | None,
    config_path: str | Path | None,
) -> GeologyProjectionPayload:
    """Project geology information from the source dataset onto the planar mesh."""
    if geology_cfg is None:
        return GeologyProjectionPayload(
            available=False,
            cell_zone_keys=tuple("" for _ in range(mesh.n_cells)),
            cell_zone_codes=tuple(0 for _ in range(mesh.n_cells)),
        )

    support = raster_support
    if support is None:
        raise ValueError("surface_topo.support is required to project geology on mesh")

    resolved_cfg = _resolve_geology_config_paths(geology_cfg, config_path=config_path)
    loaded = get_geology_data_source().load_encoded_grid_on_raster_support(
        resolved_cfg,
        raster_support=support,
    )
    cell_samples_per_axis = int(resolved_cfg.get("cell_samples_per_axis", 8))
    field = GeologyField(
        identifier=str(resolved_cfg["id"]),
        encoded_codes=loaded["encoded_codes"],
        encoded_to_zone=loaded["encoded_to_zone"],
        transform=loaded["transform"],
        crs=loaded["crs"],
        source_kind=str(loaded["source_kind"]),
        default_cell_samples_per_axis=cell_samples_per_axis,
    )
    discretization = field.on_mesh(
        mesh,
        cell_samples_per_axis=cell_samples_per_axis,
    )
    zone_keys, fractions_by_zone = discretization.weighted_components()
    zone_keys = tuple(str(zone_key) for zone_key in zone_keys)
    zone_to_code = {
        str(zone_key): int(encoded_code)
        for encoded_code, zone_key in loaded["encoded_to_zone"].items()
    }

    fractions_flat = {
        zone_key: np.asarray(fractions_by_zone[zone_key], dtype=float).reshape(-1)
        for zone_key in zone_keys
    }

    cell_zone_keys: list[str] = []
    cell_zone_codes: list[int] = []
    fraction_rows: list[GeologyFractionRow] = []
    for cell_idx in range(int(mesh.n_cells)):
        dominant_key = ""
        dominant_fraction = -1.0
        for zone_key in zone_keys:
            fraction = float(fractions_flat[zone_key][cell_idx])
            if fraction > 0.0:
                fraction_rows.append(
                    GeologyFractionRow(
                        cell_id=int(cell_idx),
                        geology_key=str(zone_key),
                        fraction=float(fraction),
                    )
                )
            if fraction > dominant_fraction + 1.0e-12 or (
                abs(fraction - dominant_fraction) <= 1.0e-12
                and dominant_key != ""
                and str(zone_key) < dominant_key
            ):
                dominant_key = str(zone_key) if fraction > 0.0 else dominant_key
                dominant_fraction = float(fraction)
        if dominant_fraction <= 0.0:
            cell_zone_keys.append("")
            cell_zone_codes.append(0)
            continue
        cell_zone_keys.append(dominant_key)
        cell_zone_codes.append(int(zone_to_code.get(dominant_key, 0)))

    return GeologyProjectionPayload(
        available=True,
        field_id=str(field.identifier),
        zone_keys=zone_keys,
        cell_zone_keys=tuple(cell_zone_keys),
        cell_zone_codes=tuple(cell_zone_codes),
        fraction_rows=tuple(fraction_rows),
        source_kind=str(loaded["source_kind"]),
        cell_samples_per_axis=int(cell_samples_per_axis),
    )


def _build_river_linework(river_trace: object | None):
    """Collapse a river-trace payload to one shapely linework object."""
    lines_attr = getattr(river_trace, "lines", None)
    river_lines = _iter_line_geometries(lines_attr)
    if not river_lines:
        return None
    return unary_union(river_lines)


def _build_river_matcher(
    *,
    river_trace: object | None,
    tolerance: float,
) -> RiverLineworkMatcher | None:
    """Build one reusable matcher for exported river edges."""
    lines_attr = getattr(river_trace, "lines", None)
    river_lines = _iter_line_geometries(lines_attr)
    if not river_lines:
        return None
    matcher = RiverLineworkMatcher(
        line_geometries=tuple(river_lines),
        tolerance=tolerance,
    )
    return matcher if matcher.available else None


def _segment_matches_river(
    segment: LineString,
    river_linework,
    *,
    tolerance: float,
) -> bool:
    """Return whether one exported edge segment belongs to the river trace."""
    if isinstance(river_linework, RiverLineworkMatcher):
        return river_linework.matches_segment(segment)
    if river_linework is None or bool(getattr(river_linework, "is_empty", True)):
        return False
    if float(river_linework.distance(segment)) > float(tolerance):
        return False
    checkpoints = (
        Point(segment.coords[0]),
        segment.interpolate(0.5, normalized=True),
        Point(segment.coords[-1]),
    )
    return all(float(river_linework.distance(point)) <= float(tolerance) for point in checkpoints)


def _build_edge_rows(
    *,
    mesh,
    cell_zone_keys: tuple[str, ...],
    river_trace: object | None,
) -> list[dict[str, object]]:
    """Build the exported edge table from mesh adjacency information."""
    edge_map: dict[tuple[int, int], list[int]] = {}
    for cell in mesh.cells:
        node_indices = tuple(int(node_idx) for node_idx in cell.node_indices)
        for idx, node_a in enumerate(node_indices):
            node_b = int(node_indices[(idx + 1) % len(node_indices)])
            key = (
                (int(node_a), int(node_b))
                if int(node_a) < int(node_b)
                else (int(node_b), int(node_a))
            )
            edge_map.setdefault(key, []).append(int(cell.index))

    span_x = float(np.nanmax(mesh.points_xy[:, 0]) - np.nanmin(mesh.points_xy[:, 0]))
    span_y = float(np.nanmax(mesh.points_xy[:, 1]) - np.nanmin(mesh.points_xy[:, 1]))
    tolerance = max(max(span_x, span_y) * 1.0e-8, 1.0e-4)
    river_matcher = _build_river_matcher(
        river_trace=river_trace,
        tolerance=tolerance,
    )
    river_linework = (
        river_matcher if river_matcher is not None else _build_river_linework(river_trace)
    )

    rows: list[dict[str, object]] = []
    for edge_id, (key, cells) in enumerate(sorted(edge_map.items())):
        node_a, node_b = key
        cell_ids = tuple(sorted(int(cell_id) for cell_id in cells))
        point_a = np.asarray(mesh.points_xy[node_a], dtype=float)
        point_b = np.asarray(mesh.points_xy[node_b], dtype=float)
        segment = LineString(
            [
                (float(point_a[0]), float(point_a[1])),
                (float(point_b[0]), float(point_b[1])),
            ]
        )
        cell_a = int(cell_ids[0])
        cell_b = None if len(cell_ids) < 2 else int(cell_ids[1])
        geology_a_key = str(cell_zone_keys[cell_a]) if cell_a < len(cell_zone_keys) else ""
        geology_b_key = (
            "" if cell_b is None or cell_b >= len(cell_zone_keys) else str(cell_zone_keys[cell_b])
        )
        if cell_b is None:
            edge_kind = "boundary"
        elif geology_a_key != "" and geology_a_key != geology_b_key:
            edge_kind = "geology_interface"
        else:
            edge_kind = "internal"
        rows.append(
            {
                "edge_id": int(edge_id),
                "node_a": int(node_a),
                "node_b": int(node_b),
                "cell_a": int(cell_a),
                "cell_b": _normalize_optional_int(cell_b),
                "length_m": float(segment.length),
                "edge_kind": str(edge_kind),
                "is_river": bool(
                    _segment_matches_river(
                        segment,
                        river_linework,
                        tolerance=tolerance,
                    )
                ),
                "geology_a_key": str(geology_a_key),
                "geology_b_key": str(geology_b_key),
            }
        )
    return rows


def _build_metadata(
    *,
    mesh,
    mesh_path: Path,
    geology_payload: GeologyProjectionPayload,
    hydraulic_properties_payload: HydraulicPropertiesPayload,
    summary: CatchmentBundleSummaryReference | None,
    domain_geographic: object,
    domain: Domain,
) -> CatchmentBundleMetadata:
    """Assemble the top-level `metadata.json` payload for one bundle."""
    surface = getattr(domain_geographic, "surface_topo", None)
    _, support = _surface_values_and_support(surface)
    topography_path = getattr(domain_geographic, "watershed_box_buff_dem", None)
    summary_path = None if summary is None else summary.output_summary_json
    return CatchmentBundleMetadata(
        {
            "bundle_schema_version": BUNDLE_SCHEMA_VERSION,
            "mesh_kind": str(mesh.kind),
            "cell_type": str(mesh.cell_type),
            "indexing": "zero_based",
            "crs": None if support is None else getattr(support, "crs", None),
            "n_nodes": int(mesh.n_nodes),
            "n_cells": int(mesh.n_cells),
            "constraints_mode": None if summary is None else summary.constraints_mode,
            "topography": {
                "node_field": "z_top",
                "cell_fields": ["z_top_centroid", "z_top_mean"],
                "source_path": None if topography_path is None else str(topography_path),
            },
            "vertical": {
                "available": True,
                "surface_name": str(getattr(domain.substratum, "name", "substratum")),
                "derived_from": "domain.depth_model",
                "node_field": "z_bottom",
                "cell_fields": ["z_bottom_centroid", "z_bottom_mean"],
                "depth_model": _serialize_depth_model(domain),
            },
            "geology": {
                "available": bool(geology_payload.available),
                "field_id": geology_payload.field_id,
                "source_kind": geology_payload.source_kind,
                "cell_samples_per_axis": geology_payload.cell_samples_per_axis,
                "zone_keys": list(geology_payload.zone_keys),
            },
            "hydraulic_properties": {
                "available": bool(hydraulic_properties_payload.available),
                "averaging": str(hydraulic_properties_payload.averaging),
                "cell_fields": [
                    "hydraulic_conductivity_m_s",
                    "storage_coefficient",
                ],
                "conductivity": {
                    "available": bool(hydraulic_properties_payload.conductivity.available),
                    "unit": "m/s",
                    "values_source": hydraulic_properties_payload.conductivity.values_source,
                    "values_csv_file": hydraulic_properties_payload.conductivity.values_csv_file,
                    "default_value": hydraulic_properties_payload.conductivity.default_value,
                    "zone_keys_defined": list(
                        hydraulic_properties_payload.conductivity.zone_keys_defined
                    ),
                    "missing_zone_keys": list(
                        hydraulic_properties_payload.conductivity.missing_zone_keys
                    ),
                },
                "storage_coefficient": {
                    "available": bool(hydraulic_properties_payload.storage_coefficient.available),
                    "unit": "-",
                    "values_source": hydraulic_properties_payload.storage_coefficient.values_source,
                    "values_csv_file": hydraulic_properties_payload.storage_coefficient.values_csv_file,
                    "default_value": hydraulic_properties_payload.storage_coefficient.default_value,
                    "zone_keys_defined": list(
                        hydraulic_properties_payload.storage_coefficient.zone_keys_defined
                    ),
                    "missing_zone_keys": list(
                        hydraulic_properties_payload.storage_coefficient.missing_zone_keys
                    ),
                },
            },
            "files": {
                "mesh": "mesh_2d.msh",
                "nodes": "nodes.csv",
                "cells": "cells.csv",
                "edges": "edges.csv",
                "cell_geology_fractions": "cell_geology_fractions.csv",
                "metadata": "metadata.json",
                "readme": "README.md",
                "mesh_summary": (
                    None
                    if summary_path is None or not Path(str(summary_path)).exists()
                    else "mesh_summary.json"
                ),
            },
            "source_mesh_path": str(mesh_path),
        }
    )


def _write_readme(path: Path, *, metadata: CatchmentBundleMetadata) -> None:
    """Write the human-facing README copied next to the bundle files."""
    metadata_mapping = metadata.to_mapping()
    geology_available = bool(metadata_mapping.get("geology", {}).get("available", False))
    hydraulic_available = bool(
        metadata_mapping.get("hydraulic_properties", {}).get("available", False)
    )
    readme = (
        "# Catchment Mesh Bundle\n\n"
        "Self-contained export for external numerical workflows.\n\n"
        "Files:\n"
        "- `mesh_2d.msh`: original planar Gmsh mesh.\n"
        "- `nodes.csv`: node coordinates, topography (`z_top`) and substratum (`z_bottom`).\n"
        "- `cells.csv`: per-cell geometry, topography, substratum, geology, and hydraulic summary.\n"
        "- `edges.csv`: edge adjacency and boundary/interface flags.\n"
        "- `cell_geology_fractions.csv`: one row per non-zero geology fraction.\n"
        "- `metadata.json`: bundle schema, CRS, and field semantics.\n"
        "\n"
        "Conventions:\n"
        "- all indices are zero-based,\n"
        "- coordinates are expressed in the CRS declared in `metadata.json`,\n"
        "- empty values in CSV mean missing / not available.\n"
        "\n"
        f"Geology exported: {'yes' if geology_available else 'no'}\n"
        f"Hydraulic properties exported: {'yes' if hydraulic_available else 'no'}\n"
    )
    path.write_text(readme, encoding="utf-8")


def export_catchment_mesh_bundle(
    *,
    mesh_path: str | Path,
    domain_geographic: object,
    domain_cfg: object | None = None,
    bundle_dir: str | Path | None = None,
    geology_cfg: CatchmentBundleGeologyExportConfig | None = None,
    hydraulic_properties_cfg: CatchmentBundleHydraulicPropertiesConfig | None = None,
    river_trace: object | None = None,
    summary: CatchmentBundleSummaryReference | None = None,
    config_path: str | Path | None = None,
) -> dict[str, Any]:
    """Export one catchment mesh bundle and return a compact summary.

    The workflow is intentionally linear:
    1. load the planar mesh and the vertical support surfaces,
    2. project geology and hydraulic properties to cells,
    3. write plain CSV/JSON tables next to a copied `.msh` file.
    """
    mesh_path_obj = Path(mesh_path).resolve()
    if not mesh_path_obj.exists():
        raise FileNotFoundError(f"Mesh file not found for bundle export: {mesh_path_obj}")

    bundle_path = (
        resolve_default_catchment_mesh_bundle_dir(mesh_path_obj)
        if bundle_dir is None
        else Path(bundle_dir).resolve()
    )
    bundle_path.mkdir(parents=True, exist_ok=True)

    # Load the reference 2D mesh and the surfaces used to derive top/bottom Z.
    mesh = load_planar_mesh(mesh_path_obj)
    surface = getattr(domain_geographic, "surface_topo", None)
    domain = _build_domain_for_bundle(surface=surface, domain_cfg=domain_cfg)
    substratum = domain.substratum
    surface_sampler = PreparedSurfaceSampler.from_surface(surface)
    substratum_sampler = PreparedSurfaceSampler.from_surface(substratum)
    point_xy = np.asarray(mesh.points_xy, dtype=float)
    node_z = surface_sampler.sample_points_xy(point_xy)
    node_z_bottom = substratum_sampler.sample_points_xy(point_xy)
    cells = mesh.cells
    centroid_xy = np.asarray([cell.centroid for cell in cells], dtype=float)
    centroid_z_top_all = surface_sampler.sample_points_xy(centroid_xy)
    centroid_z_bottom_all = substratum_sampler.sample_points_xy(centroid_xy)
    # Build the optional thematic payloads that enrich the raw geometry export.
    geology_payload = _compute_geology_payload(
        mesh=mesh,
        raster_support=surface_sampler.support,
        geology_cfg=geology_cfg,
        config_path=config_path,
    )
    hydraulic_properties_payload = _build_hydraulic_properties_payload(
        mesh=mesh,
        geology_payload=geology_payload,
        hydraulic_properties_cfg=hydraulic_properties_cfg,
        config_path=config_path,
    )
    conductivity_values = tuple(hydraulic_properties_payload.conductivity.cell_values)
    storage_values = tuple(hydraulic_properties_payload.storage_coefficient.cell_values)

    # Assemble one row per cell with geometry, elevations and optional properties.
    cell_rows: list[dict[str, object]] = []
    for cell in cells:
        vertices = np.asarray(cell.vertices, dtype=float)
        cell_index = int(cell.index)
        centroid = centroid_xy[cell_index]
        cell_node_indices = tuple(int(node_idx) for node_idx in cell.node_indices)
        cell_node_z = node_z[np.asarray(cell_node_indices, dtype=int)]
        cell_node_z_bottom = node_z_bottom[np.asarray(cell_node_indices, dtype=int)]
        centroid_z = float(centroid_z_top_all[cell_index])
        centroid_z_bottom = float(centroid_z_bottom_all[cell_index])
        mean_z = float(np.nanmean(cell_node_z)) if np.any(np.isfinite(cell_node_z)) else np.nan
        mean_z_bottom = (
            float(np.nanmean(cell_node_z_bottom))
            if np.any(np.isfinite(cell_node_z_bottom))
            else np.nan
        )
        n3_value: str | int = _NODATA_SENTINEL
        if len(cell_node_indices) > 3:
            n3_value = int(cell_node_indices[3])
        cell_rows.append(
            {
                "cell_id": int(cell.index),
                "geom_type": str(cell.kind),
                "n0": int(cell_node_indices[0]),
                "n1": int(cell_node_indices[1]),
                "n2": int(cell_node_indices[2]),
                "n3": n3_value,
                "centroid_x": float(centroid[0]),
                "centroid_y": float(centroid[1]),
                "area_m2": _polygon_area(vertices),
                "z_top_centroid": _normalize_optional_float(centroid_z),
                "z_top_mean": _normalize_optional_float(mean_z),
                "z_bottom_centroid": _normalize_optional_float(centroid_z_bottom),
                "z_bottom_mean": _normalize_optional_float(mean_z_bottom),
                "geology_code": _normalize_optional_int(
                    int(geology_payload.cell_zone_codes[cell_index])
                ),
                "geology_key": str(geology_payload.cell_zone_keys[cell_index]),
                "hydraulic_conductivity_m_s": _normalize_optional_float(
                    None
                    if cell_index >= len(conductivity_values)
                    else conductivity_values[cell_index]
                ),
                "storage_coefficient": _normalize_optional_float(
                    None if cell_index >= len(storage_values) else storage_values[cell_index]
                ),
            }
        )

    # Node/edge/fraction tables keep the bundle easy to consume from plain CSV.
    node_rows = [
        {
            "node_id": int(node_idx),
            "x": float(mesh.points_xy[node_idx, 0]),
            "y": float(mesh.points_xy[node_idx, 1]),
            "z_top": _normalize_optional_float(float(node_z[node_idx])),
            "z_bottom": _normalize_optional_float(float(node_z_bottom[node_idx])),
        }
        for node_idx in range(int(mesh.n_nodes))
    ]
    edge_rows = _build_edge_rows(
        mesh=mesh,
        cell_zone_keys=tuple(str(v) for v in geology_payload.cell_zone_keys),
        river_trace=river_trace,
    )
    fraction_rows = [row.to_mapping() for row in geology_payload.fraction_rows]

    _write_csv(
        bundle_path / "nodes.csv",
        ["node_id", "x", "y", "z_top", "z_bottom"],
        node_rows,
    )
    _write_csv(
        bundle_path / "cells.csv",
        [
            "cell_id",
            "geom_type",
            "n0",
            "n1",
            "n2",
            "n3",
            "centroid_x",
            "centroid_y",
            "area_m2",
            "z_top_centroid",
            "z_top_mean",
            "z_bottom_centroid",
            "z_bottom_mean",
            "geology_code",
            "geology_key",
            "hydraulic_conductivity_m_s",
            "storage_coefficient",
        ],
        cell_rows,
    )
    _write_csv(
        bundle_path / "edges.csv",
        [
            "edge_id",
            "node_a",
            "node_b",
            "cell_a",
            "cell_b",
            "length_m",
            "edge_kind",
            "is_river",
            "geology_a_key",
            "geology_b_key",
        ],
        edge_rows,
    )
    _write_csv(
        bundle_path / "cell_geology_fractions.csv",
        ["cell_id", "geology_key", "fraction"],
        fraction_rows,
    )

    # Metadata and companion files describe how to interpret the raw tables.
    metadata = _build_metadata(
        mesh=mesh,
        mesh_path=mesh_path_obj,
        geology_payload=geology_payload,
        hydraulic_properties_payload=hydraulic_properties_payload,
        summary=summary,
        domain_geographic=domain_geographic,
        domain=domain,
    )
    (bundle_path / "metadata.json").write_text(
        json.dumps(metadata.to_mapping(), indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )

    shutil.copy2(mesh_path_obj, bundle_path / "mesh_2d.msh")
    summary_path = None if summary is None else summary.output_summary_json
    if summary_path is not None:
        summary_path_obj = Path(str(summary_path)).resolve()
        if summary_path_obj.exists():
            shutil.copy2(summary_path_obj, bundle_path / "mesh_summary.json")

    _write_readme(bundle_path / "README.md", metadata=metadata)

    return {
        "bundle_schema_version": BUNDLE_SCHEMA_VERSION,
        "bundle_dir": str(bundle_path),
        "mesh_filename": "mesh_2d.msh",
        "n_nodes": int(mesh.n_nodes),
        "n_cells": int(mesh.n_cells),
        "n_edges": int(len(edge_rows)),
        "geology_available": bool(geology_payload.available),
        "hydraulic_properties_available": bool(hydraulic_properties_payload.available),
        "vertical_available": True,
    }


__all__ = [
    "BUNDLE_SCHEMA_VERSION",
    "CatchmentMeshBundle",
    "CatchmentMeshBundleCell",
    "CatchmentMeshBundleEdge",
    "CatchmentMeshBundleGeologyFraction",
    "CatchmentMeshBundleNode",
    "export_catchment_mesh_bundle",
    "load_catchment_mesh_bundle",
    "resolve_default_catchment_mesh_bundle_dir",
]
