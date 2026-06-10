"""MF6 SFR (streamflow routing) package builder on a DISV grid.

Turns one delineated :class:`SfrReachTrace` (spatial layer) or one explicit reach
table (``flow.sinks_sources.sfr.<id>.reaches``) into the FloPy ``ModflowGwfsfr``
arguments: PACKAGEDATA, signed CONNECTIONDATA, DIVERSIONS, PERIOD forcings and
the OBS6 spec the extractor re-keys per reach.

A trace reach is a LineString that generally spans several DISV cells, so it is
split into per-cell sub-reaches (order-preserving along the line), then the
post-split DAG is re-numbered by a Kahn topological sort so the final ``ifno``
is strictly downstream-increasing (lets MF6 run with
``maximum_picard_iterations = 1``).

SFR is lake-independent by construction: this module never imports
``builders.lake``. The optional coupling to a lake is data, one
:class:`MoverRecord` (provider ``SFR``, receiver ``LAK``) emitted for the
terminal reach when ``outflow_to_lake`` is set; ``build.py`` instantiates the
MVR package last.

Functions are pure and keyword-only, mirroring ``builders/lake.py``. They raise
plain ``ValueError`` naming the offending TOML path.
"""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any

import numpy as np

from hydromodpy.core.logging import get_logger
from hydromodpy.core.units.hydraulic_conductivity import parse_to_m_per_s
from hydromodpy.physics.flow.time_forcing import resolve_period_values_from_forcing
from hydromodpy.solver.modflow6.builders.mvr import MoverRecord
from hydromodpy.solver.modflow6.builders.period_forcing import (
    constant_forcing_value,
    forcing_to_si,
    forcing_unit,
    package_unit_conversions,
    resolve_forcing_mode,
    resolve_use_ts6,
    ts6_times_and_values,
)
from hydromodpy.solver.modflow6.builders.vertex_grid import build_vertex_grid_for_intersection
from hydromodpy.solver.modflow6.builders.wells import well_cell_to_disv
from hydromodpy.solver.modflow6.common.time_series import Ts6Series

if TYPE_CHECKING:
    from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh

logger = get_logger(__name__)

# The single SFR package name used across the GWF model (see build.py: pname="SFR").
_SFR_PACKAGE_NAME = "SFR"
# The single LAK package name (MVR receiver); a string, never an import edge.
_LAK_PACKAGE_NAME = "LAK"

# FloPy cellid for a reach not connected to the aquifer: (-1, -1) is written as
# the MF6-recommended "0 0" unconnected encoding ("none" is deprecated in 6.4.3+).
_UNCONNECTED_CELLID = (-1, -1)

# Segments shorter than this [m] are GridIntersect corner grazes, not reaches.
_MIN_SEGMENT_LENGTH = 1e-6


@dataclasses.dataclass(frozen=True)
class SfrReachRecord:
    """One MF6 reach (post-split), ready for PACKAGEDATA.

    ``cellid`` is the 0-based ``(layer, cell2d)`` pair, or ``None`` for a reach
    not connected to the aquifer. ``upstream`` / ``downstream`` hold final
    0-based ``ifno`` values; ``ifno`` increases strictly downstream.
    """

    ifno: int
    cellid: tuple[int, int] | None
    rlen: float
    rwid: float
    rgrd: float
    rtp: float
    upstream: tuple[int, ...]
    downstream: tuple[int, ...]
    ustrf: float = 1.0
    strahler: int = 1
    area_km2: float = 0.0
    is_headwater: bool = False
    is_terminal_to_lake: bool = False


@dataclasses.dataclass(frozen=True)
class ResolvedSfrNetwork:
    """One resolved SFR network: ordered reach records plus its config payload."""

    network_id: str
    reaches: tuple[SfrReachRecord, ...]
    definition: dict[str, Any]

    @property
    def downstream_increasing(self) -> bool:
        """True when every downstream connection has a strictly higher ifno."""
        return all(d > reach.ifno for reach in self.reaches for d in reach.downstream)


def _attr(payload: object, name: str) -> object:
    if isinstance(payload, Mapping):
        return payload.get(name)
    return getattr(payload, name, None)


def _length_m(value: object) -> float:
    """Coerce a Length (pint quantity or bare number) to meters."""
    to = getattr(value, "to", None)
    if callable(to):
        return float(to("m").magnitude)
    return float(getattr(value, "magnitude", value))  # type: ignore[arg-type]


def _active_sfr_definitions(model) -> dict[str, dict[str, Any]]:
    """Return the active SFR network definitions keyed by network id.

    A network is active when ``sfr`` is listed in ``flow.active_bc``. The
    payloads come from ``flow.sinks_sources['sfr']`` (config objects or runtime
    mappings carrying the binder-attached ``reach_trace``).
    """
    flow = getattr(model, "flow", None)
    if flow is None:
        return {}
    active_bc = {str(name).lower() for name in getattr(flow, "active_bc", []) or []}
    if "sfr" not in active_bc:
        return {}

    sinks_sources = getattr(flow, "sinks_sources", {})
    sfr = sinks_sources.get("sfr") if isinstance(sinks_sources, Mapping) else None
    if not isinstance(sfr, Mapping) or not sfr:
        return {}

    definitions: dict[str, dict[str, Any]] = {}
    for network_id, payload in sfr.items():
        definitions[str(network_id)] = {
            name: _attr(payload, name)
            for name in (
                "manning",
                "streambed_k",
                "streambed_k_unit",
                "streambed_thickness",
                "min_slope",
                "width",
                "connected_to_aquifer",
                "route_drainage",
                "storage",
                "headwater_inflow",
                "runoff",
                "rainfall",
                "evaporation",
                "reaches",
                "diversions",
                "outflow_to_lake",
                "outflow_mvrtype",
                "outflow_value",
                "reach_trace",
            )
        }
    return definitions


def _first_active_layer(idomain: np.ndarray, cell_id: int, nlay: int) -> int | None:
    """Return the first active layer of one column scanned from the top, or None."""
    for lay in range(nlay):
        if int(idomain[lay, cell_id]) == 1:
            return lay
    return None


def resolve_reach_line_cells(
    line,
    *,
    grid_intersect,
    location: str,
) -> list[tuple[int, float, float]]:
    """Intersect one reach LineString with the grid, preserving along-line order.

    Returns ``[(cell2d, segment_length_m, midpoint_distance_m), ...]`` ordered by
    the projected position of each within-cell segment along the line (head ->
    outlet). This deliberately does NOT reuse the lake's ``resolve_lake_cells``,
    which sorts and de-duplicates cell ids and would destroy the reach order.
    """
    result = grid_intersect.intersect(line, geo_dataframe=False)
    segments: list[tuple[float, int, float]] = []
    for row in result:
        seg_length = float(row["lengths"])
        if seg_length < _MIN_SEGMENT_LENGTH:
            continue
        shape = row["ixshapes"]
        midpoint = shape.interpolate(0.5, normalized=True)
        segments.append((float(line.project(midpoint)), int(row["cellids"]), seg_length))
    if not segments:
        raise ValueError(
            f"{location} reach polyline does not intersect any grid cell; check the "
            "network geometry CRS and the model extent."
        )
    segments.sort(key=lambda item: item[0])
    return [(cell2d, seg_length, mid) for mid, cell2d, seg_length in segments]


def _reach_width(width_cfg: object, *, strahler: int, area_km2: float, location: str) -> float:
    """Resolve one reach width [m] from the configured width law."""
    kind = str(_attr(width_cfg, "kind") or "constant")
    if kind == "constant":
        value = _attr(width_cfg, "value")
        if value is None:
            raise ValueError(f"{location}.width constant law requires a value.")
        return _length_m(value)
    if kind == "by_order":
        widths = _attr(width_cfg, "widths")
        if not isinstance(widths, Mapping) or not widths:
            raise ValueError(f"{location}.width by_order law requires a widths mapping.")
        by_order = {int(order): _length_m(width) for order, width in widths.items()}
        if strahler in by_order:
            return by_order[strahler]
        # Clamp to the declared range: a higher order takes the widest declared
        # width, a lower order the narrowest.
        below = [order for order in by_order if order < strahler]
        if below:
            return by_order[max(below)]
        return by_order[min(by_order)]
    if kind == "power_law":
        coef = float(_attr(width_cfg, "coef"))  # type: ignore[arg-type]
        exp = float(_attr(width_cfg, "exp"))  # type: ignore[arg-type]
        return float(coef * max(float(area_km2), 0.0) ** exp)
    raise ValueError(f"{location}.width kind must be constant, by_order or power_law; got {kind}.")


def resolve_sfr_networks(
    model,
    *,
    solver_mesh: SolverMesh,
) -> dict[str, ResolvedSfrNetwork]:
    """Resolve every active SFR network to its ordered reach records.

    Returns ``{}`` when no SFR boundary is active, which keeps the SFR wiring in
    ``build.py`` a no-op for models without a stream network. Reach cells come
    either from the explicit ``reaches`` table or from the binder-attached
    ``reach_trace`` intersected with the DISV mesh.
    """
    definitions = _active_sfr_definitions(model)
    if not definitions:
        return {}

    networks: dict[str, ResolvedSfrNetwork] = {}
    vertex_grid = None
    for network_id, definition in definitions.items():
        location = f"flow.sinks_sources.sfr.{network_id}"
        if definition.get("reaches"):
            records = _resolve_explicit_network(
                definition=definition, solver_mesh=solver_mesh, location=location
            )
        elif definition.get("reach_trace") is not None:
            if vertex_grid is None:
                vertex_grid = build_vertex_grid_for_intersection(solver_mesh)
            records = _resolve_trace_network(
                definition=definition,
                solver_mesh=solver_mesh,
                vertex_grid=vertex_grid,
                location=location,
            )
        else:
            raise ValueError(
                f"{location} has neither an explicit reaches table nor a bound "
                "reach_trace; run the river-network delineation step before "
                "pre-processing (geographic.river_network.enabled = true)."
            )
        _assert_reciprocal(records, location=location)
        networks[network_id] = ResolvedSfrNetwork(
            network_id=network_id, reaches=tuple(records), definition=definition
        )
    return networks


def _resolve_trace_network(
    *,
    definition: Mapping[str, Any],
    solver_mesh: SolverMesh,
    vertex_grid,
    location: str,
) -> list[SfrReachRecord]:
    """Split one delineated trace onto the DISV mesh and re-number downstream."""
    from flopy.utils import GridIntersect

    trace = definition["reach_trace"]
    parents = sorted(trace.reaches, key=lambda reach: int(reach.ifno))
    if not parents:
        raise ValueError(f"{location} reach_trace holds no reach.")

    grid_intersect = GridIntersect(vertex_grid)
    idomain = solver_mesh.idomain()
    nlay = int(solver_mesh.nlay)
    connected = definition.get("connected_to_aquifer") is not False
    min_slope = float(definition.get("min_slope") or 1e-4)
    width_cfg = definition.get("width")

    # 1. Split each parent reach into ordered per-cell sub-reaches.
    nodes: list[dict[str, Any]] = []
    edges: list[tuple[int, int]] = []
    first_sub: dict[int, int] = {}
    last_sub: dict[int, int] = {}
    for parent in parents:
        segments = resolve_reach_line_cells(
            parent.line, grid_intersect=grid_intersect, location=location
        )
        line_length = float(parent.line.length)
        rgrd = max(float(parent.rgrd), min_slope)
        rwid = _reach_width(
            width_cfg,
            strahler=int(parent.strahler),
            area_km2=float(parent.area_km2),
            location=location,
        )
        base = len(nodes)
        for cell2d, seg_length, mid_distance in segments:
            cellid: tuple[int, int] | None = None
            if connected:
                layer = _first_active_layer(idomain, cell2d, nlay)
                if layer is None:
                    raise ValueError(
                        f"{location} reach {parent.ifno} crosses cell {cell2d} whose "
                        "column is fully inactive; the reach has no aquifer cell to "
                        "exchange with."
                    )
                cellid = (int(layer), int(cell2d))
            nodes.append(
                {
                    "cellid": cellid,
                    "rlen": float(seg_length),
                    # The trace rtp sits at the parent's downstream end; walk it
                    # back up the line with the parent gradient.
                    "rtp": float(parent.rtp) + rgrd * max(line_length - float(mid_distance), 0.0),
                    "rgrd": rgrd,
                    "rwid": rwid,
                    "strahler": int(parent.strahler),
                    "area_km2": float(parent.area_km2),
                    "is_headwater": False,
                    "is_terminal_to_lake": False,
                }
            )
        first_sub[int(parent.ifno)] = base
        last_sub[int(parent.ifno)] = len(nodes) - 1
        for k in range(base, len(nodes) - 1):
            edges.append((k, k + 1))

    for parent in parents:
        if not parent.upstream:
            nodes[first_sub[int(parent.ifno)]]["is_headwater"] = True
        if bool(parent.is_terminal_to_lake):
            nodes[last_sub[int(parent.ifno)]]["is_terminal_to_lake"] = True
        for downstream in parent.downstream:
            edges.append((last_sub[int(parent.ifno)], first_sub[int(downstream)]))

    return _number_and_freeze(nodes, edges, min_slope=min_slope, location=location)


def _number_and_freeze(
    nodes: list[dict[str, Any]],
    edges: list[tuple[int, int]],
    *,
    min_slope: float,
    location: str,
) -> list[SfrReachRecord]:
    """Kahn-sort the post-split DAG, assert downstream-increasing, freeze records."""
    n = len(nodes)
    downstream_of: dict[int, list[int]] = {k: [] for k in range(n)}
    upstream_of: dict[int, list[int]] = {k: [] for k in range(n)}
    for up, down in edges:
        downstream_of[up].append(down)
        upstream_of[down].append(up)

    indegree = {k: len(upstream_of[k]) for k in range(n)}
    queue = sorted(k for k, degree in indegree.items() if degree == 0)
    order: list[int] = []
    while queue:
        node = queue.pop(0)
        order.append(node)
        inserts = []
        for down in downstream_of[node]:
            indegree[down] -= 1
            if indegree[down] == 0:
                inserts.append(down)
        for down in sorted(inserts):
            queue.append(down)
    if len(order) != n:
        raise ValueError(f"{location} post-split reach graph has a cycle; cannot route.")

    ifno_of = {node: ifno for ifno, node in enumerate(order)}
    for up, down in edges:
        if ifno_of[down] <= ifno_of[up]:
            raise ValueError(
                f"{location} post-split numbering is not downstream-increasing "
                f"(reach {ifno_of[up]} feeds reach {ifno_of[down]}); refusing to "
                "mis-route."
            )

    # Monotone-downhill clamp across the final order so no streambed top steps up
    # along a connection (sub-reach interpolation can otherwise overlap at a
    # confluence of reaches with different gradients).
    rtp = {node: float(nodes[node]["rtp"]) for node in order}
    for node in order:
        for down in downstream_of[node]:
            drop = min_slope * 0.5 * (float(nodes[node]["rlen"]) + float(nodes[down]["rlen"]))
            if rtp[down] >= rtp[node]:
                rtp[down] = rtp[node] - drop

    records: list[SfrReachRecord] = []
    for node in order:
        data = nodes[node]
        records.append(
            SfrReachRecord(
                ifno=ifno_of[node],
                cellid=data["cellid"],
                rlen=float(data["rlen"]),
                rwid=float(data["rwid"]),
                rgrd=float(data["rgrd"]),
                rtp=rtp[node],
                upstream=tuple(sorted(ifno_of[up] for up in upstream_of[node])),
                downstream=tuple(sorted(ifno_of[down] for down in downstream_of[node])),
                ustrf=float(data.get("ustrf", 1.0)),
                strahler=int(data.get("strahler", 1)),
                area_km2=float(data.get("area_km2", 0.0)),
                is_headwater=bool(data.get("is_headwater", False)),
                is_terminal_to_lake=bool(data.get("is_terminal_to_lake", False)),
            )
        )
    records.sort(key=lambda record: record.ifno)
    return records


def _resolve_explicit_network(
    *,
    definition: Mapping[str, Any],
    solver_mesh: SolverMesh,
    location: str,
) -> list[SfrReachRecord]:
    """Build reach records from an explicit ``reaches`` table (no splitting).

    Connectivity ids are 1-based in the config. Reach numbering is kept as
    declared; ``build_sfr_package_args`` falls back to the default Picard
    iterations when the declared order is not downstream-increasing.
    """
    rows = list(definition.get("reaches") or [])
    n = len(rows)
    idomain = solver_mesh.idomain()
    connected_default = definition.get("connected_to_aquifer") is not False

    records: list[SfrReachRecord] = []
    for index, row in enumerate(rows):
        row_location = f"{location}.reaches[{index}]"
        upstream = _explicit_connection_ids(_attr(row, "upstream"), n, row_location, "upstream")
        downstream = _explicit_connection_ids(
            _attr(row, "downstream"), n, row_location, "downstream"
        )
        if 0 in downstream:
            raise ValueError(
                f"{row_location} lists reach 1 as a downstream connection; MF6 signed "
                "CONNECTIONDATA cannot express a downstream link to the first reach. "
                "Number the most upstream reach first."
            )
        cellid = _explicit_reach_cellid(
            _attr(row, "cell"),
            solver_mesh=solver_mesh,
            idomain=idomain,
            connected=connected_default,
            location=row_location,
        )
        records.append(
            SfrReachRecord(
                ifno=index,
                cellid=cellid,
                rlen=_length_m(_attr(row, "length")),
                rwid=_length_m(_attr(row, "width")),
                rgrd=float(_attr(row, "slope")),  # type: ignore[arg-type]
                rtp=_length_m(_attr(row, "top")),
                upstream=upstream,
                downstream=downstream,
                ustrf=float(_attr(row, "ustrf") or 1.0),
                is_headwater=not upstream,
                is_terminal_to_lake=False,
            )
        )

    _validate_ustrf_siblings(records, location=location)
    return records


def _explicit_connection_ids(
    raw: object, reach_count: int, location: str, field: str
) -> tuple[int, ...]:
    """Translate one 1-based connection list to validated 0-based ids."""
    ids: list[int] = []
    for value in list(raw or []):  # type: ignore[call-overload]
        one_based = int(value)
        if one_based < 1 or one_based > reach_count:
            raise ValueError(
                f"{location}.{field} id {one_based} is outside the network "
                f"(1..{reach_count}, 1-based)."
            )
        ids.append(one_based - 1)
    return tuple(sorted(ids))


def _explicit_reach_cellid(
    cell: object,
    *,
    solver_mesh: SolverMesh,
    idomain: np.ndarray,
    connected: bool,
    location: str,
) -> tuple[int, int] | None:
    """Resolve one explicit reach location to a (layer, cell2d) pair, or None."""
    if cell is None or not connected:
        return None
    kind = str(_attr(cell, "kind") or "")
    if kind != "cell":
        raise ValueError(
            f"{location}.cell supports the cell-based location ([lay, row, col]) "
            "for explicit reaches; coordinate locations are reserved for the "
            "delineated path."
        )
    lay, row, col = (int(v) for v in _attr(cell, "cell"))  # type: ignore[union-attr]
    if not solver_mesh.is_structured:
        raise ValueError(f"{location}.cell [lay, row, col] addressing needs a structured grid.")
    layer, cell2d = well_cell_to_disv(ncol=int(solver_mesh.ncol), lay=lay, row=row, col=col)
    if cell2d < 0 or cell2d >= int(solver_mesh.n_cells):
        raise ValueError(f"{location}.cell is outside the grid ({solver_mesh.n_cells} cells).")
    if int(idomain[layer, cell2d]) != 1:
        raise ValueError(
            f"{location}.cell (layer {layer}, cell {cell2d}) is inactive; an SFR reach "
            "must sit on an active aquifer cell."
        )
    return (layer, cell2d)


def _validate_ustrf_siblings(records: Sequence[SfrReachRecord], *, location: str) -> None:
    """Check that the ustrf of the reaches fed by one bifurcation sum to 1.0."""
    by_ifno = {record.ifno: record for record in records}
    for record in records:
        if len(record.downstream) <= 1:
            continue
        total = sum(by_ifno[d].ustrf for d in record.downstream)
        if not math.isclose(total, 1.0, rel_tol=0.0, abs_tol=1e-6):
            raise ValueError(
                f"{location} reaches downstream of reach {record.ifno + 1} have "
                f"ustrf summing to {total}; siblings fed by one reach must sum to 1.0."
            )


def _assert_reciprocal(records: Sequence[SfrReachRecord], *, location: str) -> None:
    """Every downstream link must be mirrored by the matching upstream link."""
    by_ifno = {record.ifno: record for record in records}
    for record in records:
        for down in record.downstream:
            if record.ifno not in by_ifno[down].upstream:
                raise ValueError(
                    f"{location} connectivity is not reciprocal: reach {record.ifno} "
                    f"feeds reach {down} which does not list it upstream."
                )
        for up in record.upstream:
            if record.ifno not in by_ifno[up].downstream:
                raise ValueError(
                    f"{location} connectivity is not reciprocal: reach {record.ifno} "
                    f"is fed by reach {up} which does not list it downstream."
                )


# --------------------------------------------------------------------------- #
# DRN de-confliction.
# --------------------------------------------------------------------------- #


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


def build_drainage_mover_records(
    networks: Mapping[str, ResolvedSfrNetwork],
    *,
    drn_spd: Mapping[int, Sequence[Sequence[float]]],
    cell_centroids: np.ndarray,
    lake_cells_by_number: Mapping[int, Sequence[int]] | None = None,
) -> list[MoverRecord]:
    """Route every remaining DRN cell's discharge to its nearest water via MVR.

    The hillslope drainage exfiltrates at the land surface and converges towards
    the nearest surface water: each DRN boundary becomes an MVR provider handing
    its full outflow (FACTOR 1.0) to the closest target (planar centroid
    distance). Targets are the connected reaches AND, when the network is
    coupled to a lake, that lake's footprint: the network is truncated at the
    shoreline, so the lakeside hillslopes have no local reach. Their water still
    enters through the nearest TERMINAL reach (the lake's tributary) rather than
    through a direct DRN -> LAK record: the streamflow routing damps the stiff
    same-iteration feedback (lake stage -> lakeside heads -> drains -> lake)
    that otherwise oscillates when the spillway engages.

    The MVR provider id of a list-based package is the boundary's position in
    the period list, so the DRN stress-period data must be single-period (a
    static drain); a per-period list would renumber the providers and silently
    mis-route.
    """
    if not sfr_routes_drainage(networks):
        return []
    if len(drn_spd) != 1:
        raise ValueError(
            "flow.sinks_sources.sfr route_drainage requires a static DRN "
            f"(single-period stress data); got {len(drn_spd)} periods whose row "
            "order would renumber the MVR provider ids."
        )

    # Targets: (cell2d, reach ifno). Reach cells first; the coupled lake's
    # footprint cells are added as proxies for its nearest terminal reach.
    targets: list[tuple[int, int]] = []
    for network in networks.values():
        definition = network.definition
        if not definition.get("route_drainage"):
            continue
        terminal_cells: list[tuple[int, int]] = []
        for record in network.reaches:
            if record.cellid is None:
                continue
            targets.append((int(record.cellid[1]), int(record.ifno)))
            if record.is_terminal_to_lake:
                terminal_cells.append((int(record.cellid[1]), int(record.ifno)))
        lake_number = definition.get("outflow_to_lake")
        if lake_number is not None and lake_cells_by_number and terminal_cells:
            terminal_xy = np.asarray(
                [cell_centroids[cell2d] for cell2d, _ in terminal_cells], dtype=float
            )
            for cell2d in lake_cells_by_number.get(int(lake_number) - 1, []):
                delta = terminal_xy - cell_centroids[int(cell2d)]
                nearest = int(np.argmin(np.einsum("ij,ij->i", delta, delta)))
                targets.append((int(cell2d), terminal_cells[nearest][1]))
    if not targets:
        return []

    target_xy = np.asarray([cell_centroids[cell2d] for cell2d, _ in targets], dtype=float)

    records: list[MoverRecord] = []
    rows = next(iter(drn_spd.values()))
    for boundary_index, row in enumerate(rows):
        cell2d = int(row[1])
        delta = target_xy - cell_centroids[cell2d]
        nearest = int(np.argmin(np.einsum("ij,ij->i", delta, delta)))
        records.append(
            MoverRecord(
                provider="DRN",
                provider_id=int(boundary_index),
                receiver=_SFR_PACKAGE_NAME,
                receiver_id=int(targets[nearest][1]),
                mvrtype="FACTOR",
                value=1.0,
            )
        )
    return records


# --------------------------------------------------------------------------- #
# MVR records (SFR -> LAK coupling seam; data, not an import edge).
# --------------------------------------------------------------------------- #


def build_sfr_mover_records(
    networks: Mapping[str, ResolvedSfrNetwork],
) -> list[MoverRecord]:
    """Compile the ``outflow_to_lake`` couplings into general MVR transfers.

    EVERY terminal-to-lake reach of a coupled network provides its
    DOWNSTREAM-FLOW to the receiving lake (0-based lake number): a real
    reservoir is usually fed by several tributaries, each truncated at the
    shoreline, so one MVR record is emitted per terminal reach. An empty result
    means every network discharges out of the model (EXT-OUTFLOW).
    """
    records: list[MoverRecord] = []
    for network_id, network in networks.items():
        definition = network.definition
        lake_number = definition.get("outflow_to_lake")
        if lake_number is None:
            continue
        terminals = _terminal_reaches(network, location=f"flow.sinks_sources.sfr.{network_id}")
        mvrtype = str(definition.get("outflow_mvrtype") or "FACTOR").strip().upper()
        raw_value = definition.get("outflow_value")
        value = float(raw_value) if raw_value is not None else 1.0
        for terminal in terminals:
            records.append(
                MoverRecord(
                    provider=_SFR_PACKAGE_NAME,
                    provider_id=int(terminal.ifno),
                    receiver=_LAK_PACKAGE_NAME,
                    receiver_id=int(lake_number) - 1,
                    mvrtype=mvrtype,
                    value=value,
                )
            )
    return records


def _terminal_reaches(network: ResolvedSfrNetwork, *, location: str) -> list[SfrReachRecord]:
    """Return the reaches whose outflow feeds the lake.

    The shoreline-truncated reaches carry the flag from the delineation. With no
    flagged reach (an explicit table, or a lake-free trace), the single network
    outlet is the terminal; several unflagged outlets are ambiguous and raise.
    """
    flagged = [record for record in network.reaches if record.is_terminal_to_lake]
    if flagged:
        return flagged
    outlets = [record for record in network.reaches if not record.downstream]
    if len(outlets) != 1:
        raise ValueError(
            f"{location} has {len(outlets)} network outlets and no terminal-to-lake "
            "flag; outflow_to_lake cannot pick the feeding reach."
        )
    return outlets


# --------------------------------------------------------------------------- #
# Package args.
# --------------------------------------------------------------------------- #


def build_sfr_package_args(
    model,
    *,
    networks: Mapping[str, ResolvedSfrNetwork],
    external_mover: bool = False,
) -> dict[str, Any] | None:
    """Assemble the ``ModflowGwfsfr`` arguments for the active SFR network.

    Returns ``None`` when no network is active. The returned dict feeds
    ``flopy.mf6.ModflowGwfsfr`` plus side-channel keys popped in ``build.py``
    (``mover_records``, ``obs_continuous``, ``sfr_obs_meta``, ``ts_specs``).

    ``external_mover`` flags MVR records from OTHER packages targeting this SFR
    (a LAK spillway release or the routed hillslope drainage): the package then
    advertises MOVER and the obs spec requests the per-reach to/from-mvr series
    even with no SFR-owned mover record.
    """
    if not networks:
        return None
    if len(networks) > 1:
        raise ValueError(
            "flow.sinks_sources.sfr declares several networks; one SFR network per "
            "model is supported (merge the networks or split the model)."
        )
    network_id, network = next(iter(networks.items()))
    definition = network.definition
    location = f"flow.sinks_sources.sfr.{network_id}"
    reaches = network.reaches

    rhk = parse_to_m_per_s(
        definition.get("streambed_k") if definition.get("streambed_k") is not None else 1e-6,
        location=f"{location}.streambed_k",
        default_unit="m/s",
        explicit_unit=(
            str(definition.get("streambed_k_unit"))
            if definition.get("streambed_k_unit") is not None
            else None
        ),
    )[0]
    rbth = _length_m(
        definition.get("streambed_thickness")
        if definition.get("streambed_thickness") is not None
        else 1.0
    )
    if rbth <= 0.0:
        raise ValueError(f"{location}.streambed_thickness must be > 0, got {rbth}.")
    manning = float(definition.get("manning") if definition.get("manning") is not None else 0.035)

    diversion_rows, ndv_by_reach, diversion_period_rows = _build_diversions(
        definition, reaches, location=location
    )

    packagedata: list[list[Any]] = []
    connectiondata: list[list[Any]] = []
    for record in reaches:
        ncon = len(record.upstream) + len(record.downstream)
        cellid = record.cellid if record.cellid is not None else _UNCONNECTED_CELLID
        packagedata.append(
            [
                int(record.ifno),
                (int(cellid[0]), int(cellid[1])),
                float(record.rlen),
                float(record.rwid),
                float(record.rgrd),
                float(record.rtp),
                float(rbth),
                float(rhk),
                float(manning),
                int(ncon),
                float(record.ustrf),
                int(ndv_by_reach.get(record.ifno, 0)),
            ]
        )
        row: list[Any] = [int(record.ifno)]
        row.extend(int(up) for up in record.upstream)
        row.extend(-int(down) for down in record.downstream)
        connectiondata.append(row)

    perioddata, ts_series = build_sfr_period_data(model, network=network)
    for kper, rows in diversion_period_rows.items():
        perioddata.setdefault(kper, []).extend(rows)

    mover_records = build_sfr_mover_records({network_id: network})
    time_conversion, length_conversion = package_unit_conversions(model)
    stem = _sfr_output_stem(model)
    obs_continuous, sfr_obs_meta = build_sfr_obs_spec(
        stem=stem, network=network, has_mover=bool(mover_records) or bool(external_mover)
    )

    args: dict[str, Any] = {
        "nreaches": len(reaches),
        "packagedata": packagedata,
        "connectiondata": connectiondata,
        "time_conversion": time_conversion,
        "length_conversion": length_conversion,
        "save_flows": True,
        "print_flows": False,
        "budget_filerecord": f"{stem}.sfr.cbc",
        "budgetcsv_filerecord": f"{stem}.sfr.budget.csv",
    }
    if network.downstream_increasing:
        # Downstream-increasing numbering guarantees a single sweep resolves the
        # routing order, so MF6 can skip the extra Picard passes.
        args["maximum_picard_iterations"] = 1
    if diversion_rows:
        args["diversions"] = diversion_rows
    if perioddata:
        args["perioddata"] = perioddata
    if definition.get("storage"):
        args["storage"] = True
    if mover_records:
        args["mover_records"] = mover_records
    if mover_records or external_mover:
        args["mover"] = True
    if ts_series:
        args["ts_specs"] = ts_series
    args["obs_continuous"] = obs_continuous
    args["sfr_obs_meta"] = sfr_obs_meta
    return args


def _build_diversions(
    definition: Mapping[str, Any],
    reaches: Sequence[SfrReachRecord],
    *,
    location: str,
) -> tuple[list[list[Any]], dict[int, int], dict[int, list[list[Any]]]]:
    """Build the DIVERSIONS rows, the per-reach ndv and the divflow PERIOD rows."""
    diversions = list(definition.get("diversions") or [])
    if not diversions:
        return [], {}, {}
    if not definition.get("reaches"):
        raise ValueError(
            f"{location}.diversions requires the explicit reaches table; delineated "
            "reach ids are renumbered at build time so a config diversion cannot "
            "target them."
        )
    by_ifno = {record.ifno: record for record in reaches}
    rows: list[list[Any]] = []
    ndv_by_reach: dict[int, int] = {}
    period_rows: dict[int, list[list[Any]]] = {}
    for index, diversion in enumerate(diversions):
        div_location = f"{location}.diversions[{index}]"
        source = int(_attr(diversion, "reach") or 0) - 1
        target = int(_attr(diversion, "to_reach") or 0) - 1
        if source not in by_ifno or target not in by_ifno:
            raise ValueError(f"{div_location} reach ids are outside the network.")
        if target not in by_ifno[source].downstream:
            raise ValueError(
                f"{div_location} to_reach {target + 1} is not a downstream connection "
                f"of reach {source + 1}."
            )
        cprior = str(_attr(diversion, "cprior") or "FRACTION").strip().upper()
        idv = ndv_by_reach.get(source, 0)
        ndv_by_reach[source] = idv + 1
        rows.append([int(source), int(idv), int(target), cprior])
        divflow = _attr(diversion, "divflow")
        if divflow is not None:
            value = constant_forcing_value(divflow)
            if value is None:
                raise ValueError(
                    f"{div_location}.divflow must be a constant forcing (per-period "
                    "diversion series are not supported yet)."
                )
            si_value = (
                float(value)
                if cprior == "FRACTION"
                else float(
                    forcing_to_si(value, divflow, f"{div_location}.divflow", volumetric=True)
                )
            )
            period_rows.setdefault(0, []).append([int(source), "diversion", int(idv), si_value])
    return rows, ndv_by_reach, period_rows


def _sfr_output_stem(model) -> str:
    """Return the output file stem for SFR files (mirrors model.model_output_name)."""
    name = getattr(model, "model_output_name", None)
    if name:
        return str(name)
    return str(getattr(model, "model_name", "") or "model")


# --------------------------------------------------------------------------- #
# PERIOD forcings.
# --------------------------------------------------------------------------- #

# (keyword, config field, volumetric) for the per-network forcings. Volumetric
# forcings [m3/s] are distributed over their target reaches; rates [m/s] apply
# uniformly per reach.
_SFR_FORCINGS: tuple[tuple[str, str, bool], ...] = (
    ("inflow", "headwater_inflow", True),
    ("runoff", "runoff", True),
    ("rainfall", "rainfall", False),
    ("evaporation", "evaporation", False),
)


def build_sfr_period_data(
    model,
    *,
    network: ResolvedSfrNetwork,
) -> tuple[dict[int, list[list[Any]]], list[Ts6Series]]:
    """Build the SFR PERIOD rows and any external TS6 series for the forcings.

    ``headwater_inflow`` lands on the headwater reaches, split by drainage area
    (equally when areas are unknown). ``runoff`` is distributed over every reach
    by length fraction. ``rainfall`` / ``evaporation`` are rates applied to every
    reach unscaled. Constant forcings emit inline period-0 rows; non-constant
    forcings follow the shared TS6-vs-inline arbitration (`resolve_use_ts6`),
    with one pre-scaled TS6 series per reach when the distribution is uneven.
    """
    definition = network.definition
    reaches = network.reaches
    mode, min_periods = resolve_forcing_mode(model)
    nper = int(getattr(model, "nper", 0) or 0)
    period_rows: dict[int, list[list[Any]]] = {}
    ts_series: list[Ts6Series] = []
    location_root = f"flow.sinks_sources.sfr.{network.network_id}"

    for keyword, field, volumetric in _SFR_FORCINGS:
        forcing = definition.get(field)
        if forcing is None:
            continue
        targets = _forcing_targets(keyword, reaches)
        if not targets:
            continue
        _emit_network_forcing(
            model,
            keyword=keyword,
            forcing=forcing,
            volumetric=volumetric,
            targets=targets,
            location=f"{location_root}.{field}",
            mode=mode,
            min_periods=min_periods,
            nper=nper,
            period_rows=period_rows,
            ts_series=ts_series,
        )
    return period_rows, ts_series


def _forcing_targets(keyword: str, reaches: Sequence[SfrReachRecord]) -> dict[int, float]:
    """Return ``{ifno: scale}`` for one forcing keyword."""
    if keyword == "inflow":
        headwaters = [record for record in reaches if record.is_headwater]
        if not headwaters:
            headwaters = [record for record in reaches if not record.upstream]
        total_area = sum(record.area_km2 for record in headwaters)
        if total_area > 0.0:
            return {record.ifno: record.area_km2 / total_area for record in headwaters}
        count = len(headwaters)
        return {record.ifno: 1.0 / count for record in headwaters} if count else {}
    if keyword == "runoff":
        total_length = sum(record.rlen for record in reaches)
        if total_length <= 0.0:
            return {}
        return {record.ifno: record.rlen / total_length for record in reaches}
    # Rates (rainfall / evaporation) apply per reach, unscaled.
    return {record.ifno: 1.0 for record in reaches}


def _emit_network_forcing(
    model,
    *,
    keyword: str,
    forcing: object,
    volumetric: bool,
    targets: Mapping[int, float],
    location: str,
    mode: str,
    min_periods: int,
    nper: int,
    period_rows: dict[int, list[list[Any]]],
    ts_series: list[Ts6Series],
) -> None:
    """Append SFR PERIOD rows (inline floats or TS6 names) for one forcing."""
    value = constant_forcing_value(forcing)
    use_ts6 = resolve_use_ts6(forcing, mode=mode, nper=nper, min_periods=min_periods)
    if value is not None and not use_ts6:
        si_value = float(forcing_to_si(value, forcing, location, volumetric))
        for ifno, scale in targets.items():
            period_rows.setdefault(0, []).append([int(ifno), keyword, si_value * float(scale)])
        return

    if nper <= 0:
        return

    per_period = resolve_period_values_from_forcing(
        forcing=forcing,
        simulation_window=None if model.time_grid is None else model.time_grid.window,
        nper=nper,
        label=location,
    )
    unit = forcing_unit(forcing)
    per_period_si = tuple(
        float(forcing_to_si(raw, forcing, f"{location}[{idx}]", volumetric, explicit_unit=unit))
        for idx, raw in enumerate(per_period)
    )

    if use_ts6:
        uniform = all(float(scale) == 1.0 for scale in targets.values())
        if uniform:
            series_name = _ts6_series_name(keyword)
            for ifno in targets:
                period_rows.setdefault(0, []).append([int(ifno), keyword, series_name])
            times, values = ts6_times_and_values(model, per_period_si)
            ts_series.append(
                Ts6Series(name=series_name, times=times, values=values, interpolation="stepwise")
            )
            return
        for ifno, scale in targets.items():
            series_name = _ts6_series_name(keyword, ifno)
            period_rows.setdefault(0, []).append([int(ifno), keyword, series_name])
            scaled = tuple(value * float(scale) for value in per_period_si)
            times, values = ts6_times_and_values(model, scaled)
            ts_series.append(
                Ts6Series(name=series_name, times=times, values=values, interpolation="stepwise")
            )
        return

    # Inline expansion: one row per reach per stress period whenever the value
    # changes (period 0 always); MF6 carries each value forward.
    for ifno, scale in targets.items():
        previous: float | None = None
        for kper, si_value in enumerate(per_period_si):
            scaled = si_value * float(scale)
            if previous is None or scaled != previous:
                period_rows.setdefault(kper, []).append([int(ifno), keyword, scaled])
                previous = scaled


# Short tags keeping per-reach TS6 names inside the MF6 16-char identifier field.
_TS6_KEYWORD_TAGS = {
    "inflow": "in",
    "runoff": "ro",
    "rainfall": "rain",
    "evaporation": "evap",
}


def _ts6_series_name(keyword: str, ifno: int | None = None) -> str:
    """Return a unique, MF6-length-safe TS6 series name for one SFR forcing."""
    tag = _TS6_KEYWORD_TAGS.get(keyword, keyword[:4])
    if ifno is None:
        return f"sfr_{tag}"[:16]
    return f"sfr_{tag}_{int(ifno)}"[:16]


# --------------------------------------------------------------------------- #
# OBS6 spec for the per-reach output series.
# --------------------------------------------------------------------------- #

# Per-reach scalar observation types, mapped to the HMP-side series name the
# extractor stores. Requested by integer reach id (flopy chokes on boundname
# ids), every reach. 'sfr' (reach-aquifer exchange) only exists for connected
# reaches; ext-inflow / ext-outflow are requested everywhere and read 0 where
# unused so the extraction stays uniform.
_SFR_SCALAR_OBSTYPES: tuple[tuple[str, str], ...] = (
    ("stage", "stage"),
    ("depth", "depth"),
    ("downstream-flow", "downstream_flow"),
    ("ext-inflow", "ext_inflow"),
    ("ext-outflow", "ext_outflow"),
)


def build_sfr_obs_spec(
    *,
    stem: str,
    network: ResolvedSfrNetwork,
    has_mover: bool = False,
) -> tuple[dict[str, list[tuple[Any, ...]]], dict[str, Any]]:
    """Return ``(obs_continuous, sfr_obs_meta)`` for the SFR package.

    ``obs_continuous`` is the flopy ``continuous`` mapping ``{csv_file: [(name,
    type, id), ...]}`` with 0-based integer reach ids. ``sfr_obs_meta`` is the
    JSON-serialisable sidecar mapping each observation name to its network /
    reach / quantity so the extractor can re-key the obs CSV by
    ``(reach_ifno, totim)``.
    """
    obs_csv = f"{stem}.sfr.obs.csv"
    obslist: list[tuple[Any, ...]] = []
    entries: list[dict[str, Any]] = []

    def _add(obsname: str, obstype: str, ifno: int, quantity: str) -> None:
        obslist.append((obsname, obstype, (int(ifno),)))
        entries.append(
            {
                "obsname": obsname,
                "network_id": network.network_id,
                "reach": int(ifno),
                "quantity": quantity,
            }
        )

    for record in network.reaches:
        for obstype, quantity in _SFR_SCALAR_OBSTYPES:
            _add(f"r{record.ifno}_{quantity}", obstype, record.ifno, quantity)
        if record.cellid is not None:
            # Reach-aquifer exchange; positive = the stream loses to the aquifer.
            _add(f"r{record.ifno}_gw_exchange", "sfr", record.ifno, "gw_exchange")
        if has_mover:
            _add(f"r{record.ifno}_to_mvr", "to-mvr", record.ifno, "to_mvr")
            _add(f"r{record.ifno}_from_mvr", "from-mvr", record.ifno, "from_mvr")

    obs_continuous = {obs_csv: obslist}
    sfr_obs_meta = {
        "obs_csv": obs_csv,
        "budgetcsv": f"{stem}.sfr.budget.csv",
        "network_id": network.network_id,
        "reach_count": len(network.reaches),
        "entries": entries,
    }
    return obs_continuous, sfr_obs_meta


__all__ = [
    "ResolvedSfrNetwork",
    "SfrReachRecord",
    "build_drainage_mover_records",
    "build_sfr_mover_records",
    "build_sfr_obs_spec",
    "build_sfr_package_args",
    "build_sfr_period_data",
    "remove_drain_cells",
    "resolve_reach_line_cells",
    "resolve_sfr_networks",
    "sfr_drain_cells_to_drop",
    "sfr_routes_drainage",
]
