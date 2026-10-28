"""The catchment of a run: the basin of D at the outlet, and the polygon support.

The basin of D at the catchment outlet is computed once per build
(:func:`run_basin`), and every consumer of the run reads it. It carries the
share of each cell's area inside the delineated polygon, the weight of a
catchment total of a spatial quantity.

A model domain and a catchment are not the same surface. MODFLOW-NWT meshes the
delineated catchment, so summing a budget over the domain sums the catchment.
MODFLOW 6 meshes the buffered box, so the same sum includes the neighbouring
basins: measured on the Nancon at 25 m, 152.2 km2 of domain against 64.6 km2 of
catchment, and 2.119 m3/s of drain outflow against 0.888 m3/s inside the basin.
A discharge series compared to a gauge has to be the water that gauge sees, so
the sum is restricted to the basin of D the build stored on the model. A model
without one falls back on the old support ``polygon_covers``: the cells whose
centre the catchment polygon covers.

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
from dataclasses import replace
from typing import Any

import numpy as np

from hydromodpy.core.descent import Descent, DescentBasin, descent_basin
from hydromodpy.core.field_routing import accumulate_on_downhill_graph
from hydromodpy.core.logging import get_logger
from hydromodpy.core.stream_geometry import CATCHMENT_MISMATCH_WARNING_SHARE
from hydromodpy.spatial.geographic.delineated_catchment import catchment_outline
from hydromodpy.spatial.geographic.synthetic.config import SYNTHETIC_CATCH_DEF

__all__ = ["catchment_cell_mask", "polygon_cell_fraction", "polygon_cell_mask", "run_basin"]

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


def run_basin(geographic: object | None, solver_mesh: Any, descent: Descent) -> DescentBasin:
    """Return the basin of D at the catchment outlet, the one call of this build.

    The outlet is searched near the point the catchment was closed on (the
    snapped outlet, else the declared one), else inside the watershed polygon
    (cells whose centre it covers), else the basin is only the largest one of
    the domain. Call it before D drops its adjacency. The polygon is compared
    with the basin: a gap above ``CATCHMENT_MISMATCH_WARNING_SHARE`` of its
    area is a warning, as in the stream criterion.

    A basin that closes a catchment carries the share of each cell's area
    inside the delineated polygon (``catchment_fraction``), when the run has
    one. It weights the catchment totals of a spatial quantity and leaves the
    cells of the basin as they are.
    """
    areas = _cell_areas(solver_mesh)
    near, within = _outlet_search(geographic, solver_mesh, descent)
    seeded = _domain_is_the_catchment(geographic) and (near is not None or within is not None)
    basin = descent_basin(
        descent, cell_area_m2=areas, near=near, within=within, seeded_at_outlet=seeded
    )
    if seeded and not descent.base_level[basin.outlet]:
        raise ValueError(
            f"the outlet cell {basin.outlet} of the basin is not the cell D was seeded at: "
            "the two outlet searches of a watershed domain disagree."
        )
    if within is not None:
        _compare_with_the_polygon(basin, within, areas)
    logger.info(
        "Basin of D: %d cells (%.3f km2), outlet cell %d by rule %s, seeded at the outlet: %s.",
        int(basin.mask.sum()),
        basin.area_m2 / 1.0e6,
        basin.outlet,
        basin.rule,
        basin.seeded_at_outlet,
    )
    _count_constant_head_sinks(descent, basin, within, areas)
    if basin.is_catchment:
        fraction = polygon_cell_fraction(geographic, solver_mesh)
        if fraction is not None:
            basin = replace(basin, catchment_fraction=fraction)
            _report_the_fraction(basin, fraction, areas)
    return basin


def _report_the_fraction(basin: DescentBasin, fraction: np.ndarray, areas: np.ndarray) -> None:
    """Log how many cells the polygon outline cuts and the area the fraction weighs."""
    cut = (fraction > 0.0) & (fraction < 1.0)
    logger.info(
        "Catchment fraction: the polygon outline cuts %d cell(s), %d of them in the basin "
        "of D (%.2f %% of its cells); the polygon weighs %.3f km2 on the mesh against "
        "%.3f km2 for the basin.",
        int(cut.sum()),
        int((cut & basin.mask).sum()),
        100.0 * float((cut & basin.mask).sum()) / max(1, int(basin.mask.sum())),
        float((areas * fraction).sum()) / 1.0e6,
        float(areas[basin.mask].sum()) / 1.0e6,
    )


def _domain_is_the_catchment(geographic: object | None) -> bool:
    """Whether the active domain is the catchment itself, so D floods from its outlet."""
    # A synthetic geographic has no delineated extent: its domain is a box.
    return getattr(geographic, "domain_extent", "box") == "watershed"


def _cell_areas(solver_mesh: Any) -> np.ndarray:
    areas = np.asarray(solver_mesh.cell_areas(), dtype=float)
    return np.where(np.isfinite(areas), areas, 0.0)


def _outlet_search(
    geographic: object | None, solver_mesh: Any, descent: Descent
) -> tuple[tuple[float, float] | None, np.ndarray | None]:
    """Return ``(near, within)``: the closing point and the routable polygon cells."""
    within = polygon_cell_mask(geographic, solver_mesh)
    if within is not None:
        within = within & descent.routable
        if not np.any(within):
            within = None
    return _catchment_outlet_xy(geographic), within


def _catchment_outlet_xy(geographic: object | None) -> tuple[float, float] | None:
    """The point the catchment was closed on: the snapped outlet, else the declared one."""
    for x_name, y_name in (("x_outlet_snapped", "y_outlet_snapped"), ("x_outlet", "y_outlet")):
        x = getattr(geographic, x_name, None)
        y = getattr(geographic, y_name, None)
        if x is None or y is None:
            continue
        point = (float(x), float(y))
        if np.all(np.isfinite(point)):
            return point
    return None


def _compare_with_the_polygon(basin: DescentBasin, polygon: np.ndarray, areas: np.ndarray) -> None:
    """Log how far the basin of D lies from the watershed polygon, a warning above the share."""
    polygon_area = float(areas[polygon].sum())
    outside = basin.mask & ~polygon
    missing = polygon & ~basin.mask
    outside_share = float(areas[outside].sum()) / polygon_area if polygon_area else 0.0
    missing_share = float(areas[missing].sum()) / polygon_area if polygon_area else 0.0
    mismatch = outside_share + missing_share
    log = logger.warning if mismatch > CATCHMENT_MISMATCH_WARNING_SHARE else logger.info
    log(
        "Watershed polygon and basin of D: %d basin cells against %d in the polygon; %d "
        "basin cells outside the polygon (%.1f %% of its area), %d polygon cells outside "
        "the basin (%.1f %%).%s",
        int(basin.mask.sum()),
        int(polygon.sum()),
        int(outside.sum()),
        100.0 * outside_share,
        int(missing.sum()),
        100.0 * missing_share,
        (
            " The gap is above the warning share: the outlet may sit on another branch, "
            "or the mesh is much coarser than the DEM the polygon came from."
            if mismatch > CATCHMENT_MISMATCH_WARNING_SHARE
            else ""
        ),
    )


def _count_constant_head_sinks(
    descent: Descent, basin: DescentBasin, within: np.ndarray | None, areas: np.ndarray
) -> None:
    """Warn about the constant-head sinks of the catchment that take its upslope off the basin.

    A sink is a constant-head cell D ends at. The one the basin itself ends at
    is the outlet and is no loss. With a watershed polygon, only the sinks
    inside it count: one far outside it drains its own land.
    """
    sinks = descent.constant_head & descent.routable & (descent.receiver < 0) & ~basin.mask
    if within is not None:
        sinks &= within
    if not np.any(sinks):
        return
    drained = accumulate_on_downhill_graph(descent.metric.graph, areas)
    logger.warning(
        "Constant-head sinks of D: %d constant-head cell(s) have no lower neighbour; %.3f km2 "
        "drain into them and stay outside the basin.",
        int(sinks.sum()),
        float(drained[sinks].sum()) / 1.0e6,
    )
