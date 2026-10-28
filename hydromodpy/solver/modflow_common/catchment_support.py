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
catchment polygon covers.

The polygon is read by
:func:`hydromodpy.spatial.geographic.delineated_catchment.catchment_outline`,
against the mesh of the model: the outline the planner smoothed when the mesh
follows it, so a cell and the polygon agree, else the delineated polygon.
A synthetic geographic delineates no catchment: its box is the domain, so it
gives neither a polygon nor an outlet, and a synthetic run carries the domain
alone.
"""

from __future__ import annotations

import os
from typing import Any

import numpy as np

from hydromodpy.core.logging import get_logger
from hydromodpy.spatial.geographic.delineated_catchment import catchment_outline
from hydromodpy.spatial.geographic.synthetic.config import SYNTHETIC_CATCH_DEF

logger = get_logger(__name__)


def polygon_cell_mask(geographic: object | None, solver_mesh: Any) -> np.ndarray | None:
    """Cells whose centre the catchment polygon covers, None without a polygon.

    The old support ``polygon_covers``. The build compares the basin of D with
    it, and a model without a basin of D sums its discharge over it. The polygon
    is the outline the mesh followed (``catchment_outline``).
    """
    import shapely

    frame = catchment_outline(geographic, solver_mesh.cell_mesh)
    if frame is None:
        return None
    polygon = frame.geometry.union_all()
    shapely.prepare(polygon)
    centroids = np.asarray(solver_mesh.cell_centroids(), dtype=float).reshape(-1, 2)
    return np.asarray(shapely.covers(polygon, shapely.points(centroids)), dtype=bool)


def polygon_cell_fraction(geographic: object | None, solver_mesh: Any) -> np.ndarray | None:
    """Share of each cell's area inside the catchment polygon, None without one.

    The weight of a catchment total of a spatial quantity (GSFLOW practice):
    1 inside the polygon, 0 outside, the intersected share on its outline. The
    polygon is the outline the mesh followed (``catchment_outline``). The
    delineated one is taken in the frame of its file, which is the frame the
    solver mesh was built in, as :func:`polygon_cell_mask` assumes. A polygon
    that declares no CRS gives no fraction rather than a guessed frame.
    """
    from hydromodpy.spatial.mesh.model.derived_geometry import cell_polygons
    from hydromodpy.spatial.mesh.ops.vector_cell_mask import cell_area_fraction

    frame = catchment_outline(geographic, solver_mesh.cell_mesh)
    if frame is None:
        return None
    if frame.crs is None:
        logger.warning(
            "The catchment polygon %s declares no CRS, so the run stores no catchment "
            "fraction and its catchment totals count a boundary cell whole.",
            getattr(geographic, "watershed_shp", "?"),
        )
        return None
    polygons = cell_polygons(
        np.asarray(solver_mesh.planar_mesh.vertices, dtype=float),
        solver_mesh.cell_mesh.geometry.padded_connectivity,
    )
    return cell_area_fraction(
        polygons, list(frame.geometry), mesh_crs=frame.crs, geometry_crs=frame.crs
    )


def catchment_cell_mask(model: Any) -> np.ndarray:
    """Cells of the catchment the gauge closes on: the basin of D the model carries.

    A model on a synthetic domain sums over every cell: the domain is its own
    support, as its budget carries the domain row alone. A model without a
    basin of D (or whose basin is only the largest one of a domain with neither
    outlet nor polygon) sums over the cells whose centre the delineated
    catchment covers. That support is refused by name rather than defaulted to
    the whole domain: without the polygon nothing can say which water a gauge
    closes on, and a discharge objective scored on the wrong support optimises
    against the wrong water while looking perfectly healthy.
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
    geographic = getattr(model, "geographic", None)
    if getattr(geographic, "catch_def", None) == SYNTHETIC_CATCH_DEF:
        return _synthetic_domain_support(model)
    if basin is None:
        logger.warning(
            "Discharge observable: model %s carries no basin of D, so the drain is summed "
            "over the old support 'polygon_covers' (cells whose centre the delineated "
            "catchment covers).",
            getattr(model, "model_name", "?"),
        )
    return _polygon_support(model)


def _synthetic_domain_support(model: Any) -> np.ndarray:
    """Every cell of a synthetic domain, which delineates no catchment."""
    solver_mesh = getattr(model, "solver_mesh", None)
    if solver_mesh is None:
        raise ValueError(
            "a discharge observable needs the solver mesh to place its support on the "
            "cells, and this model carries none."
        )
    logger.info(
        "Discharge observable: model %s lies on a synthetic domain, which delineates no "
        "catchment, so the drain is summed over all its %d cells.",
        getattr(model, "model_name", "?"),
        int(solver_mesh.n_cells),
    )
    return np.ones(int(solver_mesh.n_cells), dtype=bool)


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
    mask = polygon_cell_mask(geographic, solver_mesh)
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


__all__ = [
    "catchment_cell_mask",
    "polygon_cell_fraction",
    "polygon_cell_mask",
]
