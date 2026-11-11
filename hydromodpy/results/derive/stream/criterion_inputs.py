"""The inputs of the stream criterion that a trial and a redrawn figure both read.

A calibration trial builds the criterion geometry from the model it just solved,
and a figure rebuilds it from the run that trial promoted. Both need the same
six things: the cells the mapped lines cross, the free ends of those lines, the
cells inside the catchment outline, the reference the basin is compared to, the
snapped outlet and the mean recharge. This module holds each of them once. It
takes arrays, geometries and CRS and reads neither a ``Run`` nor a
``RunContext``, so each caller passes what it holds.

The run stores what only the build knew (open water, the cells of the outline,
the mean recharge), written by ``run_outputs`` through these same functions, and
the figure reads those back. It never re-derives them from a polygon.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, Literal

import numpy as np
import pandas as pd

from hydromodpy.catchment.algorithms.network_heads import HeadCandidates, network_head_candidates
from hydromodpy.catchment.stream_network.extent import CHUNK_ELEMENTS
from hydromodpy.core.logging import get_logger
from hydromodpy.core.units import factor_to_m_per_s
from hydromodpy.mesh.cells.crossed_by_lines import line_crossing_cell_mask
from hydromodpy.mesh.cells.in_polygons import vector_cell_mask
from hydromodpy.model.forcing.recharge_rates import (
    criterion_mean_recharge,
    forcing_period_rates,
    mean_recharge_m_s,
)

if TYPE_CHECKING:
    import geopandas as gpd

    from hydromodpy.results.zarr_store.simulation_zarr import SimulationZarr

logger = get_logger(__name__)

__all__ = (
    "MappedCells",
    "basin_reference",
    "catchment_cells",
    "criterion_recharge_of_run",
    "declared_crs",
    "map_heads",
    "mapped_cells",
    "snapped_outlet",
)

CellRule = Literal["crossing", "touch"]


@dataclass(frozen=True, slots=True)
class MappedCells:
    """The mapped network drawn on the mesh cells, and what the drawing cost.

    ``n_fallback_parts`` counts the reaches that crossed no center segment and
    were kept at the cell holding their midpoint, ``n_outside_parts`` the reaches
    that entered no mesh cell and were left out. Both are zero under ``"touch"``.
    """

    mask: np.ndarray
    n_fallback_parts: int = 0
    n_outside_parts: int = 0


def mapped_cells(
    rule: str,
    lines: Sequence[Any],
    *,
    polygons: np.ndarray,
    vertices: np.ndarray,
    connectivity: np.ndarray,
    centres: np.ndarray | None = None,
    mesh_crs: Any,
    geometry_crs: Any,
) -> MappedCells:
    """Return the cells the mapped lines draw, by the crossing or the touch rule.

    ``"crossing"`` keeps the cell holding each point where a line crosses the
    segment joining two edge-sharing cell ``centres`` (needed by this rule only). ``"touch"`` keeps every
    cell the line intersects, corners included. ``"heads"`` draws no cell: the
    criterion traces the free ends down its own graph (:func:`map_heads`), so it
    is refused here.
    """
    if rule == "heads":
        raise ValueError(
            "map.drawn_by 'heads' draws the map on the criterion graph, from the free "
            "ends of the lines, so it has no cell projection here: build the network "
            "geometry with the head candidates of map_heads."
        )
    if rule == "touch":
        return MappedCells(
            mask=np.asarray(
                vector_cell_mask(
                    polygons, list(lines), mesh_crs=mesh_crs, geometry_crs=geometry_crs
                ),
                dtype=bool,
            )
        )
    if rule != "crossing":
        raise ValueError(f"map.drawn_by must be 'crossing' or 'touch', got {rule!r}.")
    if centres is None:
        raise ValueError("the crossing rule joins cell centers, and none were given.")
    crossed = line_crossing_cell_mask(
        polygons,
        vertices,
        connectivity,
        np.asarray(centres, dtype=float),
        list(lines),
        mesh_crs=mesh_crs,
        geometry_crs=geometry_crs,
    )
    return MappedCells(
        mask=np.asarray(crossed.mask, dtype=bool),
        n_fallback_parts=int(crossed.n_fallback_parts),
        n_outside_parts=int(crossed.n_outside_parts),
    )


def map_heads(
    lines: Sequence[Any],
    *,
    mesh_crs: Any,
    geometry_crs: Any,
    cut_outline: Any = None,
    cut_crs: Any = None,
    outlet_xy: tuple[float, float] | None = None,
    dam_foot: Iterable[int] = (),
) -> HeadCandidates:
    """Return the free ends of the mapped lines, with the foot of each dam as a head.

    The stream below a dam has no free end, so without ``dam_foot`` the reach
    under a reservoir is drawn only when the descent happens to leave the lake
    through the dam. ``outlet_xy`` only decides a warning about a cut end.
    """
    candidates = network_head_candidates(
        list(lines),
        mesh_crs=mesh_crs,
        geometry_crs=geometry_crs,
        cut_outline=cut_outline,
        cut_crs=cut_crs,
        outlet_xy=outlet_xy,
    )
    return replace(candidates, forced_cells=np.asarray(list(dam_foot), dtype=np.int64))


def snapped_outlet(x: Any, y: Any) -> tuple[float, float] | None:
    """Return the snapped pour point the catchment was closed on, or ``None``.

    That is the point the snap moved the declared outlet to, not the declared
    one. ``None`` for a catchment drawn as a polygon, which has no pour point.
    """
    try:
        point = (float(x), float(y))
    except (TypeError, ValueError):
        return None
    return point if bool(np.all(np.isfinite(point))) else None


def declared_crs(geographic: Any) -> str | None:
    """Return the projected CRS a geographic object declares, ``None`` when it declares none."""
    crs = getattr(geographic, "crs_project", None) or getattr(geographic, "crs_proj", None)
    return str(crs) if crs else None


def catchment_cells(
    polygons: np.ndarray, outline: gpd.GeoDataFrame | None, *, mesh_crs: Any
) -> np.ndarray | None:
    """Return the cells whose center the catchment outline covers, ``None`` without one.

    A catchment is areal, so a cell belongs to it when its center is inside. The
    touch rule would add one exterior ring of cells that lie mostly outside the
    divide, and that ring would read as a mismatch against the graph catchment
    that is not one. ``outline`` is the frame of
    :func:`hydromodpy.catchment.preprocess.delineated_catchment.catchment_outline`.
    """
    if outline is None or outline.empty or not mesh_crs:
        return None
    return np.asarray(
        vector_cell_mask(
            polygons,
            list(outline.geometry),
            mesh_crs=mesh_crs,
            geometry_crs=outline.crs,
            rule="centroid",
        ),
        dtype=bool,
    )


def basin_reference(
    basin: Any, outline_cells: np.ndarray | None, *, source: str, builds_d: bool = True
) -> np.ndarray | None:
    """Return the cells ``basin_mismatch`` is measured against.

    ``basin`` is the basin of D, read on the built model or stored with the run
    (anything with ``mask`` and ``is_catchment``). Without a basin of the
    catchment, the reference is the old one, the cells of the outline, and that
    is said once here. The largest basin of a synthetic domain is no catchment.
    ``builds_d`` is False for a backend that builds no D (Boussinesq), where the
    missing basin is expected and only informs.
    """
    if basin is not None and basin.is_catchment:
        return np.array(basin.mask, dtype=bool)
    if outline_cells is not None and basin is None:
        log = logger.warning if builds_d else logger.info
        log(
            "Network criterion: %s carries no basin of D, so the catchment mismatch is "
            "measured against the old reference 'polygon_centroid'.",
            source,
        )
    return outline_cells


def criterion_recharge_of_run(
    model: Any, fields: SimulationZarr, edges: pd.DatetimeIndex | None
) -> float | None:
    """Return the mean recharge rate the criterion reads, in m/s, or ``None`` if none is found.

    Three sources, in this order. The built model, which holds the rates its
    solver was given (a steady spin-up period at its own rate). Then the station
    forcing the run stores, put on the period ``edges`` by the rule the solver
    forcing is built by. Then the recharge budget the solver wrote, every
    timestep by its length and every cell by its area. On the monthly Nancon the
    budget gives 8.634e-9 m/s where the model gives 9.062e-9, so the order is
    part of the number. A run keeps the result once, and a figure reads it back.
    """
    if getattr(model, "recharge", None) is not None:
        try:
            return float(mean_recharge_m_s(model))
        except ValueError:
            logger.debug("The built model holds no finite recharge rate.")
    if edges is not None:
        stored = _stored_recharge_forcing_m_s(fields)
        if stored is not None:
            rates = list(forcing_period_rates(stored, edges))
            return float(criterion_mean_recharge(rates, durations=_edge_lengths_s(edges)))
    return _mean_of_the_recharge_budget(model, fields, edges)


def _stored_recharge_forcing_m_s(fields: SimulationZarr) -> pd.Series | None:
    """Return the station recharge forcing the run stores, stations averaged, in m/s.

    ``None`` when the run stores none under ``forcing/recharge``. Stations are
    averaged before the periods, as the forcing bridge averages them.
    """
    forcing = fields.root.get("forcing")
    group = forcing.get("recharge") if forcing is not None else None
    if group is None or not hasattr(group, "group_keys"):
        return None
    stations: list[pd.Series] = []
    for key in group.group_keys():
        node = group[key]
        if "timestamps" not in node or "values" not in node:
            continue
        stamps = np.asarray(node["timestamps"][:], dtype="int64").view("datetime64[ns]")
        values = np.asarray(node["values"][:], dtype="float64")
        # The data managers hand recharge over in mm/day.
        factor = factor_to_m_per_s(str(node.attrs.get("unit") or "mm/day"))
        stations.append(pd.Series(values * factor, index=pd.DatetimeIndex(stamps)))
    if not stations:
        return None
    return pd.concat(stations, axis=1).mean(axis=1)


def _edge_lengths_s(edges: pd.DatetimeIndex) -> np.ndarray:
    """Return the length of each period between its edges, in seconds."""
    return (edges[1:] - edges[:-1]).total_seconds().to_numpy(dtype=float)


def _mean_of_the_recharge_budget(
    model: Any, fields: SimulationZarr, edges: pd.DatetimeIndex | None
) -> float | None:
    """Return the mean recharge rate of the budget the solver wrote, in m/s, or ``None``.

    Every timestep counts by its length, its cells by their area, and once when
    the run has no dates for its steps. The last timestep alone is one day of a
    transient run: 4.5 times the mean on the daily Nancon run.
    """
    mesh = getattr(model, "solver_mesh", None)
    if mesh is None:
        return None
    areas = np.asarray(mesh.cell_areas(), dtype=float).reshape(-1)
    stamps = fields.read_time()
    n_steps = 1 if stamps is None else int(len(stamps))
    per_pass = max(1, CHUNK_ELEMENTS // max(1, int(areas.size)))
    rates: list[float] = []
    for first in range(0, n_steps, per_pass):
        try:
            stack = np.asarray(
                fields.read_field_range("recharge", first, min(first + per_pass, n_steps)),
                dtype=float,
            )
        except KeyError:
            # The run kept no recharge budget: there is nothing to average.
            return None
        if stack.ndim == 3:
            # Recharge is stored (time, layer, cell): sum onto the cell index
            # rather than flattening layers into extra columns.
            stack = stack.sum(axis=1)
        for recharge_m3_s in stack.reshape(stack.shape[0], -1):
            usable = np.isfinite(recharge_m3_s) & np.isfinite(areas) & (areas > 0.0)
            if np.any(usable):
                rates.append(float(recharge_m3_s[usable].sum() / areas[usable].sum()))
    durations = None
    if edges is not None and len(edges) == len(rates) + 1:
        durations = _edge_lengths_s(edges)
    try:
        return float(criterion_mean_recharge(rates, durations=durations))
    except ValueError:
        logger.debug("The recharge budget holds no finite value on a cell of finite area.")
        return None
