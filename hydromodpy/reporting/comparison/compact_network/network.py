"""Fallback reference-network helpers (gmsh parsing + external-network metrics)."""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

from .io import read_json_mapping, read_toml_mapping, resolve_recorded_path


def gmsh_physical_lines(
    mesh_path: Path,
    *,
    physical_name: str,
) -> list[list[tuple[float, float]]]:
    """Parse a gmsh .msh file and return polylines tagged with ``physical_name``."""
    lines = mesh_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    physical_tag: int | None = None
    nodes: dict[int, tuple[float, float]] = {}
    out: list[list[tuple[float, float]]] = []

    index = 0
    while index < len(lines):
        line = lines[index].strip()
        if line == "$PhysicalNames":
            count = int(lines[index + 1].strip())
            for raw in lines[index + 2 : index + 2 + count]:
                match = re.match(r'(\d+)\s+(\d+)\s+"(.*)"', raw.strip())
                if match and int(match.group(1)) == 1 and match.group(3) == physical_name:
                    physical_tag = int(match.group(2))
            index += count + 2
            continue
        if line == "$Nodes":
            count = int(lines[index + 1].strip())
            for raw in lines[index + 2 : index + 2 + count]:
                parts = raw.split()
                if len(parts) >= 4:
                    nodes[int(parts[0])] = (float(parts[1]), float(parts[2]))
            index += count + 2
            continue
        if line == "$Elements":
            count = int(lines[index + 1].strip())
            if physical_tag is None:
                return []
            for raw in lines[index + 2 : index + 2 + count]:
                parts = raw.split()
                if len(parts) < 6:
                    continue
                element_type = int(parts[1])
                if element_type not in (1, 8):
                    continue
                tag_count = int(parts[2])
                tags = [int(value) for value in parts[3 : 3 + tag_count]]
                if not tags or tags[0] != physical_tag:
                    continue
                node_ids = [int(value) for value in parts[3 + tag_count :]]
                coords = [nodes[node_id] for node_id in node_ids if node_id in nodes]
                if len(coords) >= 2:
                    out.append(coords)
            index += count + 2
            continue
        index += 1
    return out


def fallback_reference_network(
    comparison_root: Path,
    *,
    cache_ref: dict[str, object],
):
    """Load a reference hydrographic network from any available mesh bundle."""
    import geopandas as gpd
    from shapely.geometry import LineString

    cached = cache_ref.get("value")
    if cached is not None:
        return cached

    def bundle_candidates() -> list[Path]:
        manifest = read_json_mapping(comparison_root / "comparison_manifest.json")
        candidates: list[Path] = []
        simulations = manifest.get("simulations", [])
        if isinstance(simulations, list):
            for item in simulations:
                if not isinstance(item, dict):
                    continue
                config_path_raw = str(item.get("config_path") or "")
                if config_path_raw:
                    config_path = resolve_recorded_path(config_path_raw)
                    cfg = read_toml_mapping(config_path)
                    mesh_input = cfg.get("mesh_input", {})
                    if isinstance(mesh_input, dict):
                        raw_bundle = str(mesh_input.get("bundle_dir") or "")
                        if raw_bundle:
                            candidates.append(resolve_recorded_path(raw_bundle))
                run_folder_raw = str(item.get("run_folder") or "")
                if run_folder_raw:
                    run_folder = resolve_recorded_path(run_folder_raw)
                    candidates.append(run_folder / "mesh" / "mesh_catchment_bundle")
        return candidates

    default_projection = "EPSG:2154"
    for bundle_dir in bundle_candidates():
        mesh_path = bundle_dir / "mesh_2d.msh"
        metadata = read_json_mapping(bundle_dir / "metadata.json")
        current_crs = str(metadata.get("crs") or default_projection)
        files = metadata.get("files")
        if isinstance(files, dict) and files.get("mesh"):
            mesh_path = bundle_dir / str(files["mesh"])
        if not mesh_path.exists():
            continue
        lines = gmsh_physical_lines(mesh_path, physical_name="river::trace")
        if not lines:
            continue
        gdf = gpd.GeoDataFrame(
            {"role": ["reference"] * len(lines)},
            geometry=[LineString(line) for line in lines],
            crs=current_crs,
        )
        cache_ref["value"] = gdf
        return gdf

    empty = gpd.GeoDataFrame(geometry=[], crs=default_projection)
    cache_ref["value"] = empty
    return empty


def distance_metrics_with_external_network(
    run,
    network_gdf,
    *,
    variable: str,
    threshold: float = 0.0,
    mode=None,
    persistence_threshold: float = 0.5,
    timestep: int | None = None,
    network_buffer_m: float = 0.0,
) -> dict[str, float | int | str | None]:
    """Compute network-distance metrics using an externally supplied reference network."""
    import numpy as np

    from hydromodpy.results.derive.views import (
        _cell_field_active_state,
        _distance_stats,
        _finite_mean,
        _intersecting_cell_mask,
        _mesh_face_polygons,
        _nearest_distances,
        _network_geometries,
    )

    resolved_mode, values, valid, active = _cell_field_active_state(
        run,
        variable=variable,
        threshold=threshold,
        mode=mode,
        persistence_threshold=persistence_threshold,
        timestep=timestep,
    )
    polygons = _mesh_face_polygons(run)
    if polygons.size != values.size:
        raise ValueError(
            "Mesh polygon count does not match cell-field size: "
            f"mesh={polygons.size}, field={values.size}."
        )
    network_geometries = _network_geometries(
        network_gdf,
        buffer_m=float(network_buffer_m),
    )
    network_cells = _intersecting_cell_mask(polygons, network_geometries) & valid
    active_polygons = [
        polygon for polygon, is_active in zip(polygons, active, strict=True) if is_active
    ]
    active_polygons = [polygon for polygon in active_polygons if polygon is not None]
    active_centroids = [polygon.centroid for polygon in active_polygons]
    network_centroids = [
        polygon.centroid
        for polygon, is_network in zip(polygons, network_cells, strict=True)
        if is_network and polygon is not None
    ]
    sim_to_network = _distance_stats(
        _nearest_distances(active_centroids, network_geometries),
        prefix="sim_to_network",
    )
    network_to_sim = _distance_stats(
        _nearest_distances(network_centroids, active_polygons),
        prefix="network_to_sim",
    )
    sim_mean = _finite_mean(sim_to_network["sim_to_network_distance_mean_m"])
    network_mean = _finite_mean(network_to_sim["network_to_sim_distance_mean_m"])
    if sim_mean is None or network_mean is None:
        bidirectional_mean = None
        bidirectional_quadratic_mean = None
        bidirectional_absolute_difference_m = None
        distance_ratio = None
        distance_log10_ratio = None
    else:
        bidirectional_mean = float(0.5 * (sim_mean + network_mean))
        bidirectional_quadratic_mean = float(np.hypot(sim_mean, network_mean))
        bidirectional_absolute_difference_m = float(abs(sim_mean - network_mean))
        if sim_mean == 0.0 and network_mean == 0.0:
            distance_ratio = 1.0
            distance_log10_ratio = 0.0
        elif network_mean > 0.0 and sim_mean > 0.0:
            distance_ratio = float(sim_mean / network_mean)
            distance_log10_ratio = float(np.log10(distance_ratio))
        else:
            distance_ratio = None
            distance_log10_ratio = None
    return {
        "network_role": "reference",
        "source_variable": variable,
        "threshold": float(threshold),
        "mode": resolved_mode,
        "persistence_threshold": float(persistence_threshold),
        "timestep": int(timestep) if timestep is not None else -1,
        "network_buffer_m": float(network_buffer_m),
        "distance_method": "planar_cell_centroid_to_external_network",
        "catchment_cell_count": int(valid.sum()),
        "active_cell_count": int(active.sum()),
        "network_cell_count": int(network_cells.sum()),
        **sim_to_network,
        **network_to_sim,
        "bidirectional_distance_mean_m": bidirectional_mean,
        "bidirectional_distance_quadratic_mean_m": bidirectional_quadratic_mean,
        "bidirectional_distance_absolute_difference_m": bidirectional_absolute_difference_m,
        "planar_distance_ratio": distance_ratio,
        "planar_distance_log10_ratio": distance_log10_ratio,
    }


def reference_network_for_run(run, fallback_provider: Callable[[], object]):
    """Return the catalog reference network if available, else the bundle fallback."""
    try:
        reference = run.hydrographic_network("reference")
        if reference is not None and not reference.empty:
            return reference
    except Exception:
        pass
    fallback = fallback_provider()
    if fallback is None or fallback.empty:
        return None
    return fallback
