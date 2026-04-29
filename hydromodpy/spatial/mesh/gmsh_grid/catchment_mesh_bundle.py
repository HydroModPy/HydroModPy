"""Export self-contained catchment mesh bundles for external reuse.

The bundle format is intentionally plain:

- one copied planar `.msh` file,
- CSV tables for nodes, cells, edges, and geology fractions,
- one JSON metadata file describing conventions and optional payloads.

That keeps the export easy to inspect manually and easy to reuse from small
external scripts that do not want to import the full HydroModPy stack.

The geology / hydraulic-properties / river projections live in dedicated
sibling modules; this file orchestrates their results and writes the final
artifacts.
"""

from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path
from typing import Any

import numpy as np
from shapely.geometry import LineString

from hydromodpy.spatial.domain.depth_model_config import (
    ConstantThicknessDepthModel,
    FlatSubstratumDepthModel,
)
from hydromodpy.spatial.domain.domain import Domain
from hydromodpy.spatial.mesh.gmsh_grid._bundle_export_contracts import (
    CatchmentBundleGeologyExportConfig,
    CatchmentBundleHydraulicPropertiesConfig,
    CatchmentBundleMetadata,
    CatchmentBundleSummaryReference,
    GeologyProjectionPayload,
    HydraulicPropertiesPayload,
)
from hydromodpy.spatial.mesh.gmsh_grid._geology_bundle_export import _compute_geology_payload
from hydromodpy.spatial.mesh.gmsh_grid._hydraulic_properties_bundle_export import (
    _build_hydraulic_properties_payload,
)
from hydromodpy.spatial.mesh.gmsh_grid._river_bundle_export import (
    _build_river_linework,
    _build_river_matcher,
    _segment_matches_river,
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
