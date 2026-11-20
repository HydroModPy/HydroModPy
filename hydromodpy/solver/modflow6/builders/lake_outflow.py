"""How water leaves a lake: its outlets, the movers they ride and the spillway seeds."""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from typing import Any

import numpy as np

from hydromodpy.core.fields.vertical_column import top_active_layer
from hydromodpy.core.logging import get_logger
from hydromodpy.solver.modflow6.builders._lake_definitions import (
    _active_lake_definitions,
    _lake_attr,
    _scalar,
)
from hydromodpy.solver.modflow6.builders._lake_geometry import (
    downstream_of_wall,
)
from hydromodpy.solver.modflow6.builders._lake_outlets import (
    _downstream_spillway_ref,
    _outlet_couttype,
    _outlet_geometry,
    _resolve_lakeout,
    _resolve_receiver_lake,
)
from hydromodpy.solver.modflow6.builders.mvr import (
    MoverRecord,
)

logger = get_logger(__name__)


def build_lake_outlets(
    model,
    *,
    lakes: Mapping[str, dict[str, Any]],
) -> list[list[Any]]:
    """Build the OUTLETS rows for every active lake.

    Rows follow the FloPy LAK layout
    ``[outletno, lakein, lakeout, couttype, invert, width, rough, slope]`` with
    0-based ``outletno`` and ``lakein``. ``lakeout`` is ``-1`` for an external
    boundary (config ``lakeout = 0``) or the 0-based index of the downstream lake
    (config ``lakeout = N`` is the Nth lake, 1-based).

    ``invert`` / ``width`` are required for WEIR and MANNING; ``rough`` / ``slope``
    are required for MANNING and default to 0.0 otherwise; SPECIFIED outlets carry
    no geometry (their rate is supplied through ``perioddata``).
    """
    lake_index_by_id = {lake_id: idx for idx, lake_id in enumerate(lakes)}
    rows: list[list[Any]] = []
    outletno = 0
    for lake_index, (lake_id, definition) in enumerate(lakes.items()):
        outlets = definition.get("outlets") or []
        for outlet in outlets:
            couttype = _outlet_couttype(lake_id, outlet)
            lakeout = _resolve_lakeout(lake_id, outlet, lake_index_by_id)
            invert, width, rough, slope = _outlet_geometry(lake_id, couttype, outlet)
            rows.append(
                [
                    int(outletno),
                    int(lake_index),
                    int(lakeout),
                    couttype,
                    float(invert),
                    float(width),
                    float(rough),
                    float(slope),
                ]
            )
            outletno += 1
    _refuse_reciprocal_weirs(rows, lake_ids=list(lakes))
    _warn_on_lake_outlet_cycle(rows, lake_ids=list(lakes))
    return rows


# Two reciprocal WEIR crests closer than this (m) are the same crest.
_SAME_CREST_TOLERANCE_M = 1e-3


def _refuse_reciprocal_weirs(rows: Sequence[Sequence[Any]], *, lake_ids: Sequence[str]) -> None:
    """Refuse two WEIR outlets that spill into each other over the same crest.

    Above the crest each lake pushes water into the other every time step: the
    pair circulates (17.6 m3/s each way for a 0.04 m3/s net on the Cheze) and
    does not converge. Such a pair is not a spillway, so it is an input error.
    """

    def name(index: int) -> str:
        return lake_ids[index] if 0 <= index < len(lake_ids) else f"lake{index}"

    weirs = [row for row in rows if str(row[3]).upper() == "WEIR" and int(row[2]) >= 0]
    for position, first in enumerate(weirs):
        for second in weirs[position + 1 :]:
            if (
                int(first[1]) == int(second[2])
                and int(first[2]) == int(second[1])
                and abs(float(first[4]) - float(second[4])) <= _SAME_CREST_TOLERANCE_M
            ):
                raise ValueError(
                    "Reciprocal WEIR outlets with the same crest: "
                    f"outlet {int(first[0])} of lake '{name(int(first[1]))}' spills into "
                    f"lake '{name(int(first[2]))}' and outlet {int(second[0])} of lake "
                    f"'{name(int(second[1]))}' spills back, both at invert "
                    f"{float(first[4]):.3f} m. MF6 would circulate water around the pair "
                    "above the crest instead of routing it. Keep one of the two outlets, or "
                    "give them different crests."
                )


def _warn_on_lake_outlet_cycle(rows: Sequence[Sequence[Any]], *, lake_ids: Sequence[str]) -> None:
    """Report a lake-to-lake outlet loop, which MF6 solves as a circulating flow.

    Two lakes each spilling into the other is conservative (every transfer is
    counted once out and once in, so the balance still closes) but it is not a
    routing: MF6 sends water both ways every time step, and at a shared or nearly
    shared invert the pair see-saws. The circulating volume can exceed the real
    spillway discharge by orders of magnitude and then dominates both lakes'
    published ``outlet`` series and their stages. Nothing else catches it: the model
    converges and the mass balance stays clean.

    This does not change the model. Almost always the loop means one of the two
    outlets should route to the downstream reach or to the external boundary.
    """
    downstream: dict[int, set[int]] = {}
    for row in rows:
        lakein, lakeout = int(row[1]), int(row[2])
        if lakeout >= 0:
            downstream.setdefault(lakein, set()).add(lakeout)

    def name(index: int) -> str:
        return lake_ids[index] if 0 <= index < len(lake_ids) else f"lake{index}"

    reported: set[tuple[int, ...]] = set()
    for start in downstream:
        stack = [(start, (start,))]
        while stack:
            node, path = stack.pop()
            for nxt in downstream.get(node, ()):
                if nxt == start:
                    cycle = tuple(sorted(path))
                    if cycle in reported:
                        continue
                    reported.add(cycle)
                    inverts = [
                        float(row[4])
                        for row in rows
                        if int(row[1]) in cycle and int(row[2]) in cycle
                    ]
                    logger.warning(
                        "Lake outlet loop: %s route into each other, so MF6 circulates water "
                        "around the loop every time step instead of routing it downstream "
                        "(outlet inverts %s m). The balance still closes, but the lakes' "
                        "outlet series and stages carry the circulation. Route one of these "
                        "outlets to the downstream reach (mover.to_downstream_reach) or to the "
                        "external boundary (lakeout = 0).",
                        " and ".join(name(i) for i in path),
                        ", ".join(f"{value:.2f}" for value in inverts),
                    )
                elif nxt not in path:
                    stack.append((nxt, (*path, nxt)))


# The single LAK package name used across the GWF model (see build.py: pname="LAK").
_LAK_PACKAGE_NAME = "LAK"
# The single SFR package name (LAK -> SFR spillway receiver); a string, never an
# import edge to builders/sfr.py.
_SFR_PACKAGE_NAME = "SFR"


def build_lake_mover_records(
    model,
    *,
    lakes: Mapping[str, dict[str, Any]],
    downstream_reach_by_lake: Mapping[str, int] | None = None,
) -> list[MoverRecord]:
    """Compile the LAK outlet ``mover`` specs into general MVR transfers.

    Each outlet carrying a ``mover`` spec becomes one :class:`MoverRecord` with
    provider ``LAK`` outlet number (0-based, assigned in the same order as
    :func:`build_lake_outlets`). The receiver is either a lake (``mover.lake``,
    1-based, translated to its packagedata position) or an SFR reach
    (``mover.reach``, 1-based, the spillway-release direction); the config
    enforces exactly one of the two.

    An outlet routed directly via ``lakeout`` (no ``mover``) is skipped while
    still advancing the shared outlet number. The ``mvrtype`` is read and
    uppercased here but validated downstream by
    :func:`build_mvr_period_records`. An empty result means no controlled transfer
    is requested.
    """
    lake_count = len(lakes)
    records: list[MoverRecord] = []
    outletno = 0
    for lake_index, (lake_id, definition) in enumerate(lakes.items()):
        outlets = definition.get("outlets") or []
        for outlet in outlets:
            mover = _lake_attr(outlet, "mover")
            if mover is None:
                outletno += 1
                continue
            reach = _lake_attr(mover, "reach")
            if _lake_attr(mover, "to_downstream_reach"):
                receiver = _SFR_PACKAGE_NAME
                if downstream_reach_by_lake is None or lake_id not in downstream_reach_by_lake:
                    raise ValueError(
                        f"flow.sinks_sources.lakes.{lake_id} outlet mover to_downstream_reach "
                        "could not resolve a downstream SFR reach (no SFR channel below the dam?)."
                    )
                receiver_index = int(downstream_reach_by_lake[lake_id])
            elif reach is not None:
                receiver = _SFR_PACKAGE_NAME
                receiver_index = int(_scalar(reach)) - 1
                if receiver_index < 0:
                    raise ValueError(
                        f"flow.sinks_sources.lakes.{lake_id} outlet mover reach must be "
                        f">= 1 (1-based downstream reach); got {reach}."
                    )
            else:
                receiver = _LAK_PACKAGE_NAME
                receiver_index = _resolve_receiver_lake(lake_id, mover, lake_count)
                if receiver_index == lake_index:
                    raise ValueError(
                        f"flow.sinks_sources.lakes.{lake_id} outlet mover lake="
                        f"{receiver_index + 1} moves its outflow back into itself: the "
                        "water would circulate with no exit. Name the downstream lake."
                    )
            raw_mvrtype = _lake_attr(mover, "mvrtype")
            mvrtype = str(raw_mvrtype).strip().upper() if raw_mvrtype is not None else "FACTOR"
            raw_value = _lake_attr(mover, "value")
            value = _scalar(raw_value) if raw_value is not None else 1.0
            records.append(
                MoverRecord(
                    provider=_LAK_PACKAGE_NAME,
                    provider_id=int(outletno),
                    receiver=receiver,
                    receiver_id=int(receiver_index),
                    mvrtype=mvrtype,
                    value=value,
                )
            )
            outletno += 1
    return records


def resolve_spillway_seed_cells(
    model,
    *,
    lake_cells_by_id: Mapping[str, Sequence[int]],
    cell_adjacency: Sequence[set[int]],
    cell_centroids: np.ndarray,
    idomain: np.ndarray,
    mesh_top: np.ndarray,
    outlet_xy: tuple[float, float] | None,
) -> dict[str, int]:
    """Dam-toe cell for each lake whose spillway routes to the downstream reach.

    The seed is the cell at the foot of the dam: the lowest active non-lake neighbor of
    the lake's discharge point. The discharge point is the outlet mover's explicit
    ``discharge_xy`` when given, else the lake shoreline cell nearest the domain outlet.
    Feeding it to the SFR rectification extends the channel up to the dam, so the spillway
    feeds an SFR reach at the dam foot rather than a gap of hillslope DRN cells. Returns
    ``{lake_id: toe_cell}`` for the lakes that request it.

    A lake with a cutoff wall takes its foot downstream of the wall: the wall has the
    lake on its left, and only the cells on its right (:func:`downstream_of_wall`) are
    candidates, as for the HFB and the LAK seal. Without that, the lowest neighbor
    can be a bank beside the wall or behind it, and the release would enter the
    aquifer on the lake side. A wall with no such cell on the shore is refused.
    """
    seeds: dict[str, int] = {}
    centroids = np.asarray(cell_centroids, dtype=float)
    top = np.asarray(mesh_top, dtype=float).reshape(-1)
    active0 = top_active_layer(idomain) >= 0
    all_lake_cells = {int(c) for cells in lake_cells_by_id.values() for c in cells}
    for lake_id, definition in _active_lake_definitions(model).items():
        ref = _downstream_spillway_ref(definition, outlet_xy)
        if ref is None:
            continue
        ox, oy = ref
        cells = [int(c) for c in lake_cells_by_id.get(lake_id, [])]
        wall = definition.get("cutoff_wall_line")
        below = _below_the_wall(wall, centroids)

        def foot_cells(cell: int, below=below) -> list[int]:
            return [
                nb
                for nb in cell_adjacency[cell]
                if nb not in all_lake_cells and active0[nb] and (below is None or below[nb])
            ]

        shore = [c for c in cells if foot_cells(c)]
        if not shore:
            if below is not None and cells:
                raise ValueError(
                    f"flow.sinks_sources.lakes.{lake_id} spillway to_downstream_reach found "
                    "no active cell downstream of the cutoff wall on the lake shore, so the "
                    "dam foot cannot be placed below the wall. Check the wall trace and "
                    "its orientation (lake on its left)."
                )
            continue
        dam = min(shore, key=lambda c: float(np.hypot(centroids[c][0] - ox, centroids[c][1] - oy)))
        seeds[lake_id] = int(min(foot_cells(dam), key=lambda c: float(top[c])))
        logger.info(
            "Lake '%s': the spillway foot is cell %d (top %.2f m)%s.",
            lake_id,
            seeds[lake_id],
            float(top[seeds[lake_id]]),
            " downstream of the cutoff wall" if below is not None else "",
        )
    return seeds


def _below_the_wall(wall: object, centroids: np.ndarray) -> np.ndarray | None:
    """Per cell, whether its center lies downstream of the wall; None without a wall."""
    if wall is None or getattr(wall, "is_empty", True):
        return None
    return np.asarray(downstream_of_wall(wall, centroids[:, :2]), dtype=bool)


def own_lake_upstream_ifnos(
    sfr_networks: Mapping[str, Any], *, lake_ids: Sequence[str]
) -> dict[str, set[int]]:
    """Return, per lake id, every SFR reach whose flow ends in that lake.

    ``terminal_lake`` is the 1-based lake number (the 0-based position of the lake
    in ``lake_ids`` plus one). The set holds the terminal reaches and everything
    upstream of them, so a spillway routed to any of these reaches would close a
    ``LAK -> SFR -> LAK`` loop.
    """
    result: dict[str, set[int]] = {lake_id: set() for lake_id in lake_ids}
    for network in sfr_networks.values():
        by_ifno = {int(reach.ifno): reach for reach in network.reaches}
        for reach in network.reaches:
            if not (reach.is_terminal_to_lake and reach.terminal_lake is not None):
                continue
            position = int(reach.terminal_lake) - 1
            if not 0 <= position < len(lake_ids):
                continue
            seen = result[lake_ids[position]]
            stack = [int(reach.ifno)]
            while stack:
                ifno = stack.pop()
                if ifno in seen:
                    continue
                seen.add(ifno)
                stack.extend(int(up) for up in by_ifno[ifno].upstream if int(up) in by_ifno)
    return result


def resolve_downstream_spillway_reaches(
    seed_cell_by_lake: Mapping[str, int],
    *,
    reach_cell_to_ifno: Mapping[int, int],
    cell_centroids: np.ndarray,
    own_lake_terminal_ifnos: Mapping[str, Collection[int]] | None = None,
) -> dict[str, int]:
    """Map each spillway dam-toe seed to the 0-based SFR reach that receives its overflow.

    After the rectification seeds the dam toe (:func:`resolve_spillway_seed_cells`), that
    cell is itself a reach, so the receiver is exact. If it is not (rectification off, or
    the extension did not reach it), raise: the nearest reach is never a safe guess, it
    can be a tributary of the lake itself. Returns ``{lake_id: reach_ifno}``.

    ``own_lake_terminal_ifnos`` names, per lake, the reaches that already hand their
    flow BACK to that same lake, with every reach upstream of them (see
    :func:`own_lake_upstream_ifnos`). Sending a spillway to one of them would close a
    ``LAK -> SFR -> LAK`` loop: the lake would feed its own inflow, and nothing
    downstream checks it because the two mover rows are merged independently. An exact
    hit on one of them raises. Feeding a reach that terminates
    in a DIFFERENT lake stays allowed: that is a legitimate cascade (a forebay
    spilling into the main reservoir).
    """
    resolved: dict[str, int] = {}
    if not reach_cell_to_ifno:
        return resolved
    forbidden_by_lake = own_lake_terminal_ifnos or {}
    for lake_id, seed in seed_cell_by_lake.items():
        forbidden = {int(ifno) for ifno in forbidden_by_lake.get(lake_id, ())}
        if seed in reach_cell_to_ifno:
            ifno = int(reach_cell_to_ifno[seed])
            if ifno in forbidden:
                raise ValueError(
                    f"flow.sinks_sources.lakes.{lake_id} outlet mover to_downstream_reach "
                    f"resolved to reach {ifno}, which already feeds this same lake: the "
                    "overflow would circulate back into the reservoir. The dam toe is not "
                    "below this lake (a mid-basin lake), so declare the receiving reach "
                    "with an explicit spillway discharge point instead."
                )
            resolved[lake_id] = ifno
            continue
        raise ValueError(
            f"flow.sinks_sources.lakes.{lake_id} outlet mover to_downstream_reach found no "
            f"SFR reach on the dam foot (cell {seed}). The nearest reach is not used: it can "
            "be a tributary that flows back into the lake (99 % of a release returned to "
            "the reservoir on the Cheze). Enable rectify_on_mesh on the SFR network so a "
            "channel is drawn to the dam foot, or declare the receiving reach with "
            "mover.reach."
        )
    return resolved


__all__ = [
    "build_lake_mover_records",
    "build_lake_outlets",
    "resolve_downstream_spillway_reaches",
    "resolve_spillway_seed_cells",
]
