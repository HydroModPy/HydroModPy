"""Which cells the gauge closes on, for a discharge objective.

A model domain and a catchment are not the same surface. MODFLOW-NWT meshes the
delineated catchment, so summing a budget over the domain sums the catchment.
MODFLOW 6 meshes the buffered box, so the same sum includes the neighbouring
basins: measured on the Nancon at 25 m, 152.2 km2 of domain against 64.6 km2 of
catchment, and 2.119 m3/s of drain outflow against 0.888 m3/s inside the basin.

A discharge series compared to a gauge has to be the water that gauge sees, so
the sum is restricted here rather than left to the backend.
"""

from __future__ import annotations

import os
from typing import Any

import numpy as np

from hydromodpy.core.logging import get_logger

logger = get_logger(__name__)


def catchment_cell_mask(model: Any) -> np.ndarray:
    """Cells whose centre lies inside the delineated catchment.

    Refused by name rather than defaulted to the whole domain: without the
    polygon nothing can say which water a gauge closes on, and a discharge
    objective scored on the wrong support optimises against the wrong water
    while looking perfectly healthy.
    """
    from shapely.geometry import Point
    from shapely.prepared import prep

    geographic = getattr(model, "geographic", None)
    shp = getattr(geographic, "watershed_shp", None)
    if not shp or not os.path.exists(str(shp)):
        raise ValueError(
            "a discharge observable needs the delineated catchment to know which water "
            f"the gauge closes on, and geographic.watershed_shp points to nothing ({shp!r}). "
            "The model domain is not the catchment on a buffered grid: summing the drain "
            "over the domain would score the neighbouring basins too."
        )
    solver_mesh = getattr(model, "solver_mesh", None)
    if solver_mesh is None:
        raise ValueError(
            "a discharge observable needs the solver mesh to place the catchment on the "
            "cells, and this model carries none."
        )

    import geopandas as gpd

    gdf = gpd.read_file(str(shp))
    if gdf.empty:
        raise ValueError(f"the delineated catchment {shp!r} holds no geometry.")
    prepared = prep(gdf.geometry.union_all())
    centroids = np.asarray(solver_mesh.cell_centroids(), dtype=float)
    mask = np.fromiter(
        (prepared.covers(Point(float(x), float(y))) for x, y in centroids),
        dtype=bool,
        count=len(centroids),
    )
    if not mask.any():
        raise ValueError(
            "the delineated catchment covers no cell centre of this mesh: check that the "
            "watershed polygon and the mesh share a CRS."
        )
    logger.info(
        "Discharge observable: summing the drain over %d of %d cells, the %.1f%% of the "
        "domain the catchment covers.",
        int(mask.sum()),
        int(mask.size),
        100.0 * float(mask.mean()),
    )
    return mask


__all__ = ["catchment_cell_mask"]
