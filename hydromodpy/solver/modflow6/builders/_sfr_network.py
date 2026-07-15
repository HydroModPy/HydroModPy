"""Network-resolution internals behind ``resolve_sfr_networks``.

Private helpers that turn one delineated trace or one explicit reach table into
the ordered :class:`SfrReachRecord` list: payload accessors, the width law, the
per-cell trace split, the mesh rectification, the Kahn topological numbering and
the connectivity assertions.

Runtime construction of :class:`SfrReachRecord` and the call to the public
``resolve_reach_line_cells`` are done through function-local imports of
``builders.sfr`` so the module-load graph stays a one-way DAG
(``sfr -> _sfr_network``); the dataclasses stay defined in ``builders.sfr``.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any

import numpy as np

from hydromodpy.core.logging import get_logger
from hydromodpy.solver.modflow6.builders.wells import well_cell_to_disv

if TYPE_CHECKING:
    from hydromodpy.solver.modflow6.builders.sfr import SfrReachRecord
    from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh

logger = get_logger(__name__)


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
                "lake_feeder_snap",
                "outlet_keepout",
                "rectify_on_mesh",
                "rectify_stub_max_upstream",
                "rectify_min_component_cells",
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


def _rectify_network_on_mesh(
    records: list[SfrReachRecord],
    *,
    solver_mesh: SolverMesh,
    lake_number_of: Mapping[int, int],
    min_slope: float,
    max_stub_upstream: int,
    min_component_cells: int,
    spillway_seeds: set[int],
    location: str,
) -> list[SfrReachRecord]:
    """Rectify one network's reach cells on the mesh (SFD channel + stub pruning).

    Builds the mesh face adjacency and the set of boundary cells (a cell touching an
    inactive neighbour or a mesh edge, where a reach may leave the model), re-derives the
    single-flow-direction channel, and re-numbers the resulting graph.
    """
    from hydromodpy.solver.modflow6.builders.sfr_rectify import rectify_reach_graph
    from hydromodpy.spatial.mesh.model.cell_adjacency import build_planar_cell_adjacency

    n_cells = int(solver_mesh.n_cells)
    adjacency = build_planar_cell_adjacency(solver_mesh.planar_mesh, n_cells)
    idomain = solver_mesh.idomain()
    nlay = int(solver_mesh.nlay)
    active0 = idomain[0] > 0
    boundary_cells = {
        i
        for i in range(n_cells)
        if active0[i] and (len(adjacency[i]) < 3 or any(not active0[j] for j in adjacency[i]))
    }
    nodes, edges = rectify_reach_graph(
        records,
        mesh_top=np.asarray(solver_mesh.top, dtype=float).reshape(-1),
        cell_adjacency=adjacency,
        cell_centroids=solver_mesh.cell_centroids(),
        lake_cell_to_number=dict(lake_number_of),
        boundary_cells=boundary_cells,
        idomain=idomain,
        nlay=nlay,
        location=location,
        max_stub_upstream=max_stub_upstream,
        min_component_cells=min_component_cells,
        spillway_seeds={c for c in spillway_seeds if 0 <= int(c) < n_cells},
    )
    return _number_and_freeze(nodes, edges, min_slope=min_slope, location=location)


def _resolve_trace_network(
    *,
    definition: Mapping[str, Any],
    solver_mesh: SolverMesh,
    vertex_grid,
    location: str,
    lake_cell2d: frozenset[int] = frozenset(),
    lake_number_of: Mapping[int, int] | None = None,
) -> list[SfrReachRecord]:
    """Split one delineated trace onto the DISV mesh and re-number downstream."""
    lake_number_of = lake_number_of or {}
    from flopy.utils import GridIntersect

    from hydromodpy.solver.modflow6.builders.sfr import resolve_reach_line_cells

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

    # 1. Split each parent reach into ordered per-cell sub-reaches, TRUNCATING at
    # the lake footprint: a reach that routes into a lake (e.g. once the DEM is
    # hydro-conditioned so streams flow through the reservoir) is cut at its first
    # lake cell and flagged terminal-to-lake, so no reach sits on a LAK cell and its
    # flow is handed to the lake by MVR at the shoreline instead of double-counting.
    nodes: list[dict[str, Any]] = []
    edges: list[tuple[int, int]] = []
    first_sub: dict[int, int | None] = {}
    last_sub: dict[int, int | None] = {}
    cut_lake_of: dict[int, int | None] = {}  # parent -> lake it was cut at (terminal)
    in_lake_lake_of: dict[int, int | None] = {}  # parent entirely inside a lake -> lake
    for parent in parents:
        ifno = int(parent.ifno)
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
        cut_lake: int | None = None
        for cell2d, seg_length, mid_distance in segments:
            if lake_cell2d and int(cell2d) in lake_cell2d:
                # reached the lake footprint: stop here, drop this cell and every
                # cell downstream of it (they belong to the lake, not the stream).
                cut_lake = lake_number_of.get(int(cell2d))
                break
            cellid: tuple[int, int] | None = None
            if connected:
                layer = _first_active_layer(idomain, cell2d, nlay)
                if layer is None:
                    # The reach crosses a cell outside the active aquifer (e.g. a
                    # boundary reach when the domain is masked to the watershed).
                    # Keep it as a routing-only, aquifer-disconnected sub-reach
                    # (cellid stays None) instead of failing: it still conveys and
                    # routes flow, it just exchanges no baseflow where there is no
                    # aquifer cell.
                    logger.warning(
                        "%s reach %s crosses inactive cell %s; routing it as an "
                        "aquifer-disconnected reach (no baseflow there).",
                        location,
                        parent.ifno,
                        cell2d,
                    )
                else:
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
                    "terminal_lake": None,
                }
            )
        if len(nodes) == base:
            # No sub-reach survived: the reach starts inside a lake. Record which lake
            # so its upstream neighbours become the shoreline terminal.
            first_sub[ifno] = None
            last_sub[ifno] = None
            if cut_lake is not None:
                in_lake_lake_of[ifno] = cut_lake
            elif segments:
                in_lake_lake_of[ifno] = lake_number_of.get(int(segments[0][0]))
            continue
        first_sub[ifno] = base
        last_sub[ifno] = len(nodes) - 1
        for k in range(base, len(nodes) - 1):
            edges.append((k, k + 1))
        cut_lake_of[ifno] = cut_lake

    for parent in parents:
        ifno = int(parent.ifno)
        first = first_sub.get(ifno)
        if first is None:
            continue
        last = last_sub[ifno]
        if not parent.upstream:
            nodes[first]["is_headwater"] = True
        cut = cut_lake_of.get(ifno)
        if cut is not None:
            nodes[last]["is_terminal_to_lake"] = True
            nodes[last]["terminal_lake"] = cut
            continue  # cut at the lake: it terminates here, no downstream edges
        if bool(parent.is_terminal_to_lake):
            nodes[last]["is_terminal_to_lake"] = True
            nodes[last]["terminal_lake"] = parent.terminal_lake
        for downstream in parent.downstream:
            d_first = first_sub.get(int(downstream))
            if d_first is None:
                # the downstream reach is inside a lake: this is the shoreline
                # terminal, tag it with that lake and drop the into-lake link.
                nodes[last]["is_terminal_to_lake"] = True
                lake = in_lake_lake_of.get(int(downstream))
                if lake is not None:
                    nodes[last]["terminal_lake"] = lake
                continue
            edges.append((last, d_first))

    return _number_and_freeze(nodes, edges, min_slope=min_slope, location=location)


def _number_and_freeze(
    nodes: list[dict[str, Any]],
    edges: list[tuple[int, int]],
    *,
    min_slope: float,
    location: str,
) -> list[SfrReachRecord]:
    """Kahn-sort the post-split DAG, assert downstream-increasing, freeze records."""
    from hydromodpy.solver.modflow6.builders.sfr import SfrReachRecord

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
                terminal_lake=data.get("terminal_lake"),
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
    from hydromodpy.solver.modflow6.builders.sfr import SfrReachRecord

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
