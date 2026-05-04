"""Metrics for simulated active stream networks.

The metrics in this module operate on the common HydroModPy concepts:

- a simulated active network is a computed cell mask derived from a persisted
  field, usually ``accumulation_flux``;
- a reference network is a persisted vector hydrographic-network role.

The distance metric implemented here is deliberately planar and cell-based. It
is not the downslope DEM-routing metric from Abherve et al.; it is a stable
first diagnostic that works with the simulation artifacts currently stored in
the result catalog.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from shapely.geometry.base import BaseGeometry

    from hydromodpy.results.run import Run


def _mesh_face_polygons(sim: Run) -> np.ndarray:
    """Return one Shapely polygon per mesh face."""
    from shapely.geometry import Polygon

    mesh = sim.mesh
    vertices = np.asarray(mesh.vertices)
    face_node_connectivity = np.asarray(mesh.face_node_connectivity)
    polygons = []
    for row in face_node_connectivity:
        nodes = row[row >= 0] if row.dtype.kind in "iu" else row[~np.isnan(row)]
        if nodes.size < 3:
            polygons.append(None)
            continue
        polygon = Polygon(vertices[nodes.astype(int), :2])
        polygons.append(polygon if polygon.is_valid and not polygon.is_empty else None)
    return np.asarray(polygons, dtype=object)


def _flatten_geometries(geometries: Iterable[BaseGeometry]) -> list[BaseGeometry]:
    """Flatten geometry collections into concrete Shapely geometries."""
    flattened: list[BaseGeometry] = []
    for geometry in geometries:
        if geometry is None or geometry.is_empty:
            continue
        parts = getattr(geometry, "geoms", None)
        if parts is None:
            flattened.append(geometry)
        else:
            flattened.extend(_flatten_geometries(parts))
    return flattened


def _nearest_distances(
    sources: Iterable[BaseGeometry],
    targets: list[BaseGeometry],
) -> list[float]:
    """Return distance from each source geometry to its nearest target."""
    from shapely.strtree import STRtree

    target_geometries = [target for target in targets if target is not None and not target.is_empty]
    if not target_geometries:
        return []
    tree = STRtree(target_geometries)
    distances: list[float] = []
    for source in sources:
        if source is None or source.is_empty:
            continue
        nearest = tree.nearest(source)
        if nearest is None:
            continue
        target = target_geometries[int(nearest)]
        distances.append(float(source.distance(target)))
    return distances


def _network_geometries(network_gdf, *, buffer_m: float = 0.0) -> list[BaseGeometry]:
    """Return vector-network geometries, optionally buffered in model units."""
    if network_gdf is None or network_gdf.empty:
        return []
    geometries = network_gdf.geometry.dropna()
    if geometries.empty:
        return []
    if buffer_m > 0.0:
        geometries = geometries.buffer(float(buffer_m))
    return _flatten_geometries(geometries)


def _intersecting_cell_mask(
    polygons: np.ndarray,
    geometries: list[BaseGeometry],
) -> np.ndarray:
    """Return cells whose polygon intersects any of ``geometries``."""
    from shapely.strtree import STRtree

    mask = np.zeros(polygons.shape[0], dtype=bool)
    if not geometries:
        return mask
    tree = STRtree(geometries)
    for idx, polygon in enumerate(polygons):
        if polygon is None:
            continue
        if tree.query(polygon, predicate="intersects").size:
            mask[idx] = True
    return mask


def _distance_stats(distances: list[float], *, prefix: str) -> dict[str, float | int | None]:
    """Return stable summary statistics for one directed distance sample."""
    if not distances:
        return {
            f"{prefix}_sample_count": 0,
            f"{prefix}_distance_mean_m": None,
            f"{prefix}_distance_median_m": None,
            f"{prefix}_distance_p95_m": None,
            f"{prefix}_distance_max_m": None,
        }
    values = np.asarray(distances, dtype="float64")
    return {
        f"{prefix}_sample_count": int(values.size),
        f"{prefix}_distance_mean_m": float(np.mean(values)),
        f"{prefix}_distance_median_m": float(np.median(values)),
        f"{prefix}_distance_p95_m": float(np.percentile(values, 95.0)),
        f"{prefix}_distance_max_m": float(np.max(values)),
    }


def _finite_mean(value: object) -> float | None:
    """Return a finite float or ``None``."""
    if value is None:
        return None
    parsed = float(value)
    return parsed if np.isfinite(parsed) else None


def simulated_active_network_distance_metrics(
    sim: Run,
    *,
    network_role: str = "reference",
    variable: str = "accumulation_flux",
    threshold: float = 0.0,
    mode: str | None = None,
    persistence_threshold: float = 0.5,
    timestep: int | None = None,
    network_buffer_m: float = 0.0,
) -> dict[str, float | int | str | None]:
    """Return planar bidirectional distances between active cells and a network.

    Distances are computed in model/map units as follows:

    - simulated-to-network: centroid distance from each active simulated cell to
      the selected vector hydrographic network;
    - network-to-simulated: centroid distance from each mesh cell intersected by
      the selected vector network to the union of active simulated cell
      polygons.

    This metric is useful for current regression and visual diagnostics, while
    leaving room for a later ``downslope`` implementation that follows DEM flow
    paths as in Abherve et al.
    """
    from hydromodpy.results import views

    resolved_mode = views.resolve_simulated_active_network_mode(sim, mode)
    values = views.simulated_active_network_mask(
        sim,
        variable=variable,
        threshold=threshold,
        mode=resolved_mode,
        persistence_threshold=persistence_threshold,
        timestep=timestep,
    )
    valid = np.isfinite(values)
    if resolved_mode == "persistence":
        active = values >= float(persistence_threshold)
    else:
        active = values > 0.5
    active = active & valid

    polygons = _mesh_face_polygons(sim)
    if polygons.size != values.size:
        raise ValueError(
            "Mesh polygon count does not match simulated active-network field size: "
            f"mesh={polygons.size}, field={values.size}."
        )

    network_gdf = sim.hydrographic_network(network_role)
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

    sim_to_network_distances = _nearest_distances(
        active_centroids,
        network_geometries,
    )
    network_to_sim_distances = _nearest_distances(
        network_centroids,
        active_polygons,
    )

    sim_to_network = _distance_stats(
        sim_to_network_distances,
        prefix="sim_to_network",
    )
    network_to_sim = _distance_stats(
        network_to_sim_distances,
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
        "network_role": network_role,
        "source_variable": variable,
        "threshold": float(threshold),
        "mode": resolved_mode,
        "persistence_threshold": float(persistence_threshold),
        "timestep": int(timestep) if timestep is not None else -1,
        "network_buffer_m": float(network_buffer_m),
        "distance_method": "planar_cell_centroid_to_network",
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
