"""DRN de-confliction and the hillslope-drainage MVR routing.

Private helpers behind the public ``sfr_drain_cells_to_drop`` /
``remove_drain_cells`` / ``sfr_routes_drainage`` / ``watershed_drainage_cell_mask``
/ ``build_drainage_mover_records`` re-exported from ``builders.sfr``. The routing
walks the receivers of the descent D (``core.descent``), handed in as an array.
It also owns the two MF6 package-name literals shared by both mover builders (the
SFR->LAK one lives in ``builders.sfr``); they are strings, never an import edge
to a package.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING

import numpy as np

from hydromodpy.core.logging import get_logger
from hydromodpy.solver.modflow6.builders.mvr import MoverRecord

if TYPE_CHECKING:
    from hydromodpy.solver.modflow6.builders.sfr import ResolvedSfrNetwork

logger = get_logger(__name__)

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
    this catchment's streams and lake.
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
    receiver: np.ndarray,
    basin_cell_mask: np.ndarray,
    face_adjacency: Sequence[set[int]],
    mesh_top: np.ndarray,
    lake_cells_by_number: Mapping[int, Sequence[int]] | None = None,
) -> list[MoverRecord]:
    """Route every basin DRN cell to the FIRST water its descent reaches.

    ``receiver`` is the descent D: a filled copy of the model top on the
    descended graph, so every routable cell holds a path down to an outlet. Each
    DRN cell of the basin becomes an MVR provider handing its full outflow
    (FACTOR 1.0) to the first connected reach cell or the first lake cell its
    receiver chain meets. Lakes are sinks for this walk, whatever D does with
    them, and every declared lake is a candidate, not only ``outflow_to_lake``.
    A chain that reaches -1 first leaves the model: its cell keeps a plain DRN.

    On a quad mesh D steps diagonally, so a chain can cross a reach line between
    two reach cells that only touch at a corner. ``face_adjacency`` (shared
    faces) detects that step: when both cells flanking a diagonal step are reach
    cells, the walk ends on the one lower on the solver top ``mesh_top``.

    ``basin_cell_mask`` (bool, indexed by cell2d) restricts routing to the basin
    of D. A DRN cell outside it drains to a neighbouring basin and keeps a plain
    DRN, so the aquifer heads are unchanged and only the destination differs.

    The MVR provider id of a list-based package is the boundary's position in
    the period list, so the DRN stress-period data must be a single static
    period: a per-period list would renumber the providers and silently
    mis-route. Skipped cells keep their row index, which keeps the others aligned.
    """
    if not sfr_routes_drainage(networks):
        return []
    if len(drn_spd) != 1:
        raise ValueError(
            "flow.sinks_sources.sfr route_drainage requires a static DRN "
            f"(single-period stress data); got {len(drn_spd)} periods whose row "
            "order would renumber the MVR provider ids."
        )

    reach_cell_to_ifno: dict[int, int] = {}
    routed_reaches: set[int] = set()
    for network in networks.values():
        if not network.definition.get("route_drainage"):
            continue
        for record in network.reaches:
            if record.cellid is not None:
                reach_cell_to_ifno.setdefault(int(record.cellid[1]), int(record.ifno))
                routed_reaches.add(int(record.ifno))
    lake_cell_to_number: dict[int, int] = {}
    if lake_cells_by_number:
        for lake_number, cells in lake_cells_by_number.items():
            for cell2d in cells:
                lake_cell_to_number.setdefault(int(cell2d), int(lake_number))
    if not reach_cell_to_ifno and not lake_cell_to_number:
        return []

    rows = next(iter(drn_spd.values()))
    drn_cells = np.array([int(r[1]) for r in rows], dtype=int)
    keep = np.flatnonzero(np.asarray(basin_cell_mask, dtype=bool)[drn_cells])
    top = np.asarray(mesh_top, dtype=float).reshape(-1)

    def crossed_reach(cell: int, nxt: int) -> int | None:
        """The lower reach cell flanking a diagonal step, when both flanks are reaches."""
        if nxt in face_adjacency[cell]:
            return None
        flanks = face_adjacency[cell] & face_adjacency[nxt]
        if len(flanks) < 2 or not all(flank in reach_cell_to_ifno for flank in flanks):
            return None
        return min(flanks, key=lambda flank: (float(top[flank]), flank))

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
            if cell in seen:
                raise ValueError(f"The descent cycles at cell {cell}: D must be acyclic.")
            seen.add(cell)
            path.append(cell)
            nxt = int(receiver[cell])
            if nxt < 0:
                break
            if nxt not in reach_cell_to_ifno and nxt not in lake_cell_to_number:
                flank = crossed_reach(cell, nxt)
                if flank is not None:
                    result = (_SFR_PACKAGE_NAME, reach_cell_to_ifno[flank])
                    break
            cell = nxt
        for visited_cell in path:
            target_of[visited_cell] = result
        return result

    records: list[MoverRecord] = []
    n_reach = n_lake = 0
    fed_reaches: set[int] = set()
    for boundary_index in keep.tolist():
        target = descent_target(int(drn_cells[boundary_index]))
        if target is None:
            continue
        pkg, target_id = target
        if pkg == _SFR_PACKAGE_NAME:
            n_reach += 1
            fed_reaches.add(int(target_id))
        else:
            n_lake += 1
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

    n_basin = int(keep.size)
    logger.info(
        "Drainage routing on the descent: %d of %d basin DRN cells routed (%.1f %%), "
        "%d to a reach, %d to a lake, %d kept plain; %d of %d reach(es) of the routed "
        "network(s) receive no drainage.",
        len(records),
        n_basin,
        100.0 * len(records) / n_basin if n_basin else 0.0,
        n_reach,
        n_lake,
        n_basin - len(records),
        len(routed_reaches - fed_reaches),
        len(routed_reaches),
    )
    return records
