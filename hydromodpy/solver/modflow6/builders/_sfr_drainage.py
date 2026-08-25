"""DRN de-confliction and the hillslope-drainage MVR routing.

Private helpers behind the public ``sfr_drain_cells_to_drop`` /
``remove_drain_cells`` / ``sfr_routes_drainage`` / ``watershed_drainage_cell_mask``
/ ``build_drainage_mover_records`` re-exported from ``builders.sfr``. It also owns
the two MF6 package-name literals shared by both mover builders (the SFR->LAK one
lives in ``builders.sfr``); they are strings, never an import edge to a package.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING

import numpy as np

from hydromodpy.solver.modflow6.builders.mvr import MoverRecord

if TYPE_CHECKING:
    from hydromodpy.solver.modflow6.builders.sfr import ResolvedSfrNetwork

# The single SFR package name used across the GWF model (see build.py: pname="SFR").
_SFR_PACKAGE_NAME = "SFR"
# The single LAK package name (MVR receiver); a string, never an import edge.
_LAK_PACKAGE_NAME = "LAK"


def sfr_drain_cells_to_drop(networks: Mapping[str, ResolvedSfrNetwork]) -> set[int]:
    """Return the cell2d ids hosting a connected reach (their DRN rows are dropped).

    The legacy NWT path zeroed ``drain_array[sfr_map > 0]``; the MF6 equivalent
    removes the DRN entries coincident with SFR reaches so catchment baseflow
    discharges into the stream instead of leaking out of the model.
    """
    cells: set[int] = set()
    for network in networks.values():
        for record in network.reaches:
            if record.cellid is not None:
                cells.add(int(record.cellid[1]))
    return cells


def remove_drain_cells(
    drn_spd: dict[int, list[list[float]]],
    *,
    cells: set[int],
) -> dict[int, list[list[float]]]:
    """Drop the DRN rows whose cell2d is occupied by an SFR reach.

    Rows follow the flat DISV layout ``[lay, cell2d, elev, cond]`` produced by
    ``build_drain_stress_period_data``.
    """
    if not cells:
        return drn_spd
    return {
        kper: [row for row in rows if int(row[1]) not in cells] for kper, rows in drn_spd.items()
    }


def sfr_routes_drainage(networks: Mapping[str, ResolvedSfrNetwork]) -> bool:
    """Return whether one active network asks for the DRN -> SFR routing."""
    return any(bool(network.definition.get("route_drainage")) for network in networks.values())


def watershed_drainage_cell_mask(
    watershed_geometry: object,
    cell_centroids: np.ndarray,
) -> np.ndarray:
    """Boolean (n_cells,) mask, True where a cell centroid lies in the watershed.

    Used to keep hillslope DRN routing inside the topographic catchment: DRN
    cells in the surrounding buffer model neighbouring basins and must not feed
    this catchment's streams and lake (see ``build_drainage_mover_records``).
    """
    from shapely.geometry import Point
    from shapely.prepared import prep

    prepared = prep(watershed_geometry)
    centroids = np.asarray(cell_centroids, dtype=float)
    return np.fromiter(
        (prepared.covers(Point(float(x), float(y))) for x, y in centroids),
        dtype=bool,
        count=len(centroids),
    )


def build_drainage_mover_records(
    networks: Mapping[str, ResolvedSfrNetwork],
    *,
    drn_spd: Mapping[int, Sequence[Sequence[float]]],
    cell_centroids: np.ndarray,
    mesh_top: np.ndarray,
    cell_adjacency: Sequence[set[int]],
    lake_cells_by_number: Mapping[int, Sequence[int]] | None = None,
    watershed_cell_mask: np.ndarray | None = None,
) -> list[MoverRecord]:
    """Route every in-watershed DRN cell to the FIRST water its flow path reaches.

    The hillslope drainage exfiltrates at the land surface and follows the
    topography downhill. Each in-watershed DRN boundary becomes an MVR provider
    handing its full outflow (FACTOR 1.0) to the target its steepest-descent path
    on ``mesh_top`` first meets: the first connected reach cell OR the first lake
    cell, whichever the water reaches first (a D8-style single-flow-direction on
    the mesh face graph ``cell_adjacency``). This attributes the drainage to the
    water body it physically reaches, not the nearest one by planar distance, so an
    upstream forebay collects its own catchment instead of the drainage jumping to a
    larger neighbouring lake. EVERY declared lake is a candidate sink, not only the
    network's ``outflow_to_lake``. A cell whose descent dead-ends in a closed
    depression or exits the domain before meeting either stays a plain DRN; enable
    ``[<backend>.sgrid] condition_top`` to fill the DEM->Voronoi projection pits so
    every hillslope cell has a descending path to its water body first.

    ``watershed_cell_mask`` (a boolean array indexed by cell2d) restricts routing
    to the topographic watershed. A DRN cell in the buffer (mask False) belongs
    to a neighbouring basin: its exfiltration must leave the model as a plain
    DRN, not feed this catchment's streams and lake. Skipping its MVR record
    leaves the DRN row untouched, so the aquifer heads (and the inter-basin
    exchange the buffer models) are unchanged; only the water's destination
    differs. ``None`` keeps every remaining DRN cell routed.

    The MVR provider id of a list-based package is the boundary's position in
    the period list, so the DRN stress-period data must be single-period (a
    static drain); a per-period list would renumber the providers and silently
    mis-route. Skipping buffer cells preserves that alignment because it keeps
    the full row order and only drops the record for the skipped index.
    """
    if not sfr_routes_drainage(networks):
        return []
    if len(drn_spd) != 1:
        raise ValueError(
            "flow.sinks_sources.sfr route_drainage requires a static DRN "
            f"(single-period stress data); got {len(drn_spd)} periods whose row "
            "order would renumber the MVR provider ids."
        )

    # Candidate sinks: the connected reach cells of every route_drainage network and
    # EVERY declared lake's footprint cells (0-based number = the key). A DRN cell
    # routes to the first of these its downhill path meets, so a forebay upstream of a
    # larger lake still collects the catchment that physically drains through it.
    reach_cell_to_ifno: dict[int, int] = {}
    for network in networks.values():
        if not network.definition.get("route_drainage"):
            continue
        for record in network.reaches:
            if record.cellid is not None:
                reach_cell_to_ifno.setdefault(int(record.cellid[1]), int(record.ifno))
    lake_cell_to_number: dict[int, int] = {}
    if lake_cells_by_number:
        for lake_number, cells in lake_cells_by_number.items():
            for cell2d in cells:
                lake_cell_to_number.setdefault(int(cell2d), int(lake_number))
    if not reach_cell_to_ifno and not lake_cell_to_number:
        return []

    rows = next(iter(drn_spd.values()))
    drn_cells = np.array([int(r[1]) for r in rows], dtype=int)
    if watershed_cell_mask is not None:
        # Buffer cells drain to a neighbouring basin and leave the model as a plain
        # DRN (no MVR record). Their row index is dropped here; the surviving
        # provider_id still equals the original boundary index, so the other
        # providers stay aligned.
        keep = np.where(np.asarray(watershed_cell_mask, dtype=bool)[drn_cells])[0]
    else:
        keep = np.arange(drn_cells.shape[0])

    top = np.asarray(mesh_top, dtype=float).reshape(-1)
    n_cells = top.shape[0]
    sinks = set(reach_cell_to_ifno) | set(lake_cell_to_number)
    # Steepest-descent single-flow-direction receiver on the mesh face graph: the
    # neighbour with the largest positive slope (dz / centroid distance). Sinks and
    # local minima have no receiver (-1); condition_top fills the projection pits so a
    # hillslope cell descends to its water body instead of a closed depression.
    receiver = np.full(n_cells, -1, dtype=int)
    for cell in range(n_cells):
        if cell in sinks:
            continue
        z = top[cell]
        cx, cy = float(cell_centroids[cell][0]), float(cell_centroids[cell][1])
        best, best_slope = -1, 0.0
        for nb in cell_adjacency[cell]:
            dz = z - top[nb]
            if dz <= 0.0:
                continue
            dist = math.hypot(cx - float(cell_centroids[nb][0]), cy - float(cell_centroids[nb][1]))
            slope = dz / dist if dist > 0.0 else dz
            if slope > best_slope:
                best_slope, best = slope, int(nb)
        receiver[cell] = best

    # Follow each cell's descent to the first sink it meets, memoised per cell.
    target_of: dict[int, tuple[str, int] | None] = {}

    def descent_target(start: int) -> tuple[str, int] | None:
        path: list[int] = []
        seen: set[int] = set()
        cell = start
        result: tuple[str, int] | None = None
        while True:
            if cell in target_of:
                result = target_of[cell]
                break
            if cell in lake_cell_to_number:
                result = (_LAK_PACKAGE_NAME, lake_cell_to_number[cell])
                break
            if cell in reach_cell_to_ifno:
                result = (_SFR_PACKAGE_NAME, reach_cell_to_ifno[cell])
                break
            nxt = int(receiver[cell])
            if nxt < 0 or nxt in seen:
                break
            seen.add(cell)
            path.append(cell)
            cell = nxt
        for visited_cell in path:
            target_of[visited_cell] = result
        return result

    records: list[MoverRecord] = []
    for boundary_index in keep.tolist():
        target = descent_target(int(drn_cells[boundary_index]))
        if target is None:
            continue
        pkg, target_id = target
        records.append(
            MoverRecord(
                provider="DRN",
                provider_id=int(boundary_index),
                receiver=pkg,
                receiver_id=int(target_id),
                mvrtype="FACTOR",
                value=1.0,
            )
        )
    return records
