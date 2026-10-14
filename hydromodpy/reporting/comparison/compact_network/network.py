"""Fallback reference-network helpers (river lines of the mesh families, external-network metrics)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from hydromodpy.results.errors import FieldNotFoundError, RunNotFoundError

from .io import read_json_mapping, resolve_recorded_path

if TYPE_CHECKING:
    from hydromodpy.results.run import Run

RIVER_FAMILY = "rivers"
"""Name of the cell family that holds the river chains of a mesh."""


def river_polylines(run: Run) -> list[np.ndarray]:
    """Return one ``(n, 2)`` polyline per river chain of the mesh of ``run``.

    A chain runs through the centres of its cells, upstream to downstream. A chain
    of a single cell has no line and is left out.

    Raises
    ------
    FieldNotFoundError
        The run was sealed before the mesh stored its families.
    """
    from hydromodpy.results.run.mesh_families import mesh_families

    cells = mesh_families(run).cells
    rivers = cells[cells["family"] == RIVER_FAMILY].sort_values(["chain_id", "position"])
    if rivers.empty:
        return []
    centres = run.mesh.cell_centers()
    return [
        centres[chain["cell_id"].to_numpy()]
        for _, chain in rivers.groupby("chain_id", sort=True)
        if len(chain) >= 2
    ]


def fallback_reference_network(
    comparison_root: Path,
    *,
    cache_ref: dict[str, object],
):
    """Load a reference river network from the mesh families of the compared runs.

    The first run whose mesh stored river chains gives the network, in the CRS of
    its mesh. A run sealed before the families were stored gives none.
    """
    import geopandas as gpd
    from shapely.geometry import LineString

    from hydromodpy.results.catalog import Catalog

    cached = cache_ref.get("value")
    if cached is not None:
        return cached

    manifest = read_json_mapping(comparison_root / "comparison_manifest.json")
    simulations = manifest.get("simulations", [])
    for item in simulations if isinstance(simulations, list) else []:
        if not isinstance(item, dict) or not item.get("run_folder") or not item.get("sim_id"):
            continue
        catalog = Catalog(resolve_recorded_path(str(item["run_folder"])), read_only=True)
        try:
            try:
                run = catalog[str(item["sim_id"])]
                lines = river_polylines(run)
            except (RunNotFoundError, FieldNotFoundError):
                # A vanished run, or one sealed before the families: no line from it.
                continue
            crs = run.mesh.crs
        finally:
            catalog.close()
        if not lines or crs is None:
            continue
        gdf = gpd.GeoDataFrame(
            {"role": ["reference"] * len(lines)},
            geometry=[LineString(line) for line in lines],
            crs=crs,
        )
        cache_ref["value"] = gdf
        return gdf

    empty = gpd.GeoDataFrame(geometry=[], crs=None)
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
    from hydromodpy.results.derive import views

    return views.cell_field_network_distance_metrics(
        run,
        variable=variable,
        threshold=threshold,
        mode=mode,
        persistence_threshold=persistence_threshold,
        timestep=timestep,
        network_buffer_m=network_buffer_m,
        distance_method="planar_cell_centroid_to_external_network",
        network_gdf=network_gdf,
    )


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
