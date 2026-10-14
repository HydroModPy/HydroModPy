"""Which cells the gauge closes on, for a discharge objective.

A model domain and a catchment are not the same surface. MODFLOW-NWT meshes the
delineated catchment, so summing a budget over the domain sums the catchment.
MODFLOW 6 meshes the buffered box, so the same sum includes the neighbouring
basins: measured on the Nancon at 25 m, 152.2 km2 of domain against 64.6 km2 of
catchment, and 2.119 m3/s of drain outflow against 0.888 m3/s inside the basin.

A discharge series compared to a gauge has to be the water that gauge sees, so
the sum is restricted here rather than left to the backend. The support is the
basin of the descent D the build stored on the model. A model without one falls
back on the old support ``polygon_covers``: the cells whose centre the
delineated catchment polygon covers.
"""

from __future__ import annotations

import os
from typing import Any

import numpy as np

from hydromodpy.core.logging import get_logger

logger = get_logger(__name__)


def polygon_cell_mask(geographic: object, cell_centroids: np.ndarray) -> np.ndarray | None:
    """Cells whose centre the delineated catchment polygon covers, None without a polygon.

    The old support ``polygon_covers``. The build compares the basin of D with
    it, and a model without a basin of D sums its discharge over it.
    """
    import shapely

    shp = getattr(geographic, "watershed_shp", None)
    if not shp or not os.path.exists(str(shp)):
        return None
    import geopandas as gpd

    gdf = gpd.read_file(str(shp))
    if gdf.empty:
        return None
    polygon = gdf.geometry.union_all()
    shapely.prepare(polygon)
    centroids = np.asarray(cell_centroids, dtype=float).reshape(-1, 2)
    return np.asarray(shapely.covers(polygon, shapely.points(centroids)), dtype=bool)


def catchment_cell_mask(model: Any) -> np.ndarray:
    """Cells of the catchment the gauge closes on: the basin of D the model carries.

    A model without a basin of D (or whose basin is only the largest one of a
    domain with neither outlet nor polygon) sums over the cells whose centre
    the delineated catchment covers. That support is refused by name rather
    than defaulted to the whole domain: without the polygon nothing can say
    which water a gauge closes on, and a discharge objective scored on the
    wrong support optimises against the wrong water while looking perfectly
    healthy.
    """
    basin = getattr(model, "descent_basin", None)
    if basin is not None and basin.is_catchment:
        mask = np.asarray(basin.mask, dtype=bool)
        logger.info(
            "Discharge observable: summing the drain over the basin of D, %d of %d cells "
            "(%.3f km2), outlet cell %d.",
            int(mask.sum()),
            int(mask.size),
            float(basin.area_m2) / 1.0e6,
            int(basin.outlet),
        )
        return mask
    if basin is None:
        logger.warning(
            "Discharge observable: model %s carries no basin of D, so the drain is summed "
            "over the old support 'polygon_covers' (cells whose centre the delineated "
            "catchment covers).",
            getattr(model, "model_name", "?"),
        )
    return _polygon_support(model)


def _polygon_support(model: Any) -> np.ndarray:
    """The old support ``polygon_covers``, refused without a polygon or a mesh."""
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
    mask = polygon_cell_mask(geographic, solver_mesh.cell_centroids())
    if mask is None:
        raise ValueError(f"the delineated catchment {shp!r} holds no geometry.")
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


__all__ = ["catchment_cell_mask", "polygon_cell_mask"]
