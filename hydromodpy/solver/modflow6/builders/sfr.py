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
plain ``ValueError`` naming the offending TOML path. The network-resolution,
DRN-drainage and PERIOD/OBS internals live in the sibling ``_sfr_network`` /
``_sfr_drainage`` / ``_sfr_period`` modules; the two shared dataclasses stay
defined here so their dotted paths (``builders.sfr.SfrReachRecord`` /
``ResolvedSfrNetwork``) are stable.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any

import numpy as np

from hydromodpy.core.logging import get_logger
from hydromodpy.core.units.hydraulic_conductivity import parse_to_m_per_s
from hydromodpy.solver.modflow6.builders._sfr_drainage import (
    _LAK_PACKAGE_NAME,
    _SFR_PACKAGE_NAME,
    build_drainage_mover_records,
    remove_drain_cells,
    sfr_drain_cells_to_drop,
    sfr_routes_drainage,
    watershed_drainage_cell_mask,
)
from hydromodpy.solver.modflow6.builders._sfr_network import (
    _active_sfr_definitions,
    _assert_reciprocal,
    _attr,
    _length_m,
    _rectify_network_on_mesh,
    _resolve_explicit_network,
    _resolve_trace_network,
)
from hydromodpy.solver.modflow6.builders._sfr_period import (
    build_sfr_obs_spec,
    build_sfr_period_data,
)
from hydromodpy.solver.modflow6.builders.mvr import MoverRecord
from hydromodpy.solver.modflow6.builders.period_forcing import (
    constant_forcing_value,
    forcing_to_si,
    package_unit_conversions,
)
from hydromodpy.solver.modflow6.builders.vertex_grid import build_vertex_grid_for_intersection

if TYPE_CHECKING:
    from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh

logger = get_logger(__name__)

# FloPy cellid for a reach not connected to the aquifer: (-1, -1) is written as
# the MF6-recommended "0 0" unconnected encoding ("none" is deprecated in 6.4.3+).
_UNCONNECTED_CELLID = (-1, -1)

# Segments shorter than this [m] are GridIntersect corner grazes, not reaches.
_MIN_SEGMENT_LENGTH = 1e-6

# Minimum clearance [m] the streambed bottom (rtp - rbth) keeps above the cell bottom
# (MF6 rejects an SFR reach whose bed sinks below its aquifer cell).
_RTP_ABOVE_BOTTOM_M = 0.1


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
    terminal_lake: int | None = None


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


def resolve_sfr_networks(
    model,
    *,
    solver_mesh: SolverMesh,
    lake_cells_by_number: Mapping[int, Sequence[int]] | None = None,
    spillway_seeds: set[int] = frozenset(),
) -> dict[str, ResolvedSfrNetwork]:
    """Resolve every active SFR network to its ordered reach records.

    Returns ``{}`` when no SFR boundary is active, which keeps the SFR wiring in
    ``build.py`` a no-op for models without a stream network. Reach cells come
    either from the explicit ``reaches`` table or from the binder-attached
    ``reach_trace`` intersected with the DISV mesh. ``lake_cells_by_number`` (0-based
    LAK numbers) truncates trace reaches at the lake footprint so none sits on a lake
    cell (needed once the DEM is hydro-conditioned to route streams through a lake).
    """
    definitions = _active_sfr_definitions(model)
    if not definitions:
        return {}

    lake_cell2d: frozenset[int] = frozenset()
    lake_number_of: dict[int, int] = {}
    if lake_cells_by_number:
        for lake_num, cells in lake_cells_by_number.items():
            for cell2d in cells:
                lake_number_of[int(cell2d)] = int(lake_num) + 1  # terminal_lake is 1-based
        lake_cell2d = frozenset(lake_number_of)

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
                lake_cell2d=lake_cell2d,
                lake_number_of=lake_number_of,
            )
        else:
            raise ValueError(
                f"{location} has neither an explicit reaches table nor a bound "
                "reach_trace; run the river-network delineation step before "
                "pre-processing (geographic.river_network.enabled = true)."
            )
        if definition.get("rectify_on_mesh"):
            stub_max = definition.get("rectify_stub_max_upstream")
            min_comp = definition.get("rectify_min_component_cells")
            records = _rectify_network_on_mesh(
                records,
                solver_mesh=solver_mesh,
                lake_number_of=lake_number_of,
                min_slope=float(definition.get("min_slope") or 1e-4),
                max_stub_upstream=int(stub_max) if stub_max is not None else 2,
                min_component_cells=int(min_comp) if min_comp is not None else 2,
                spillway_seeds=spillway_seeds,
                location=location,
            )
        _assert_reciprocal(records, location=location)
        networks[network_id] = ResolvedSfrNetwork(
            network_id=network_id, reaches=tuple(records), definition=definition
        )
    return networks


# --------------------------------------------------------------------------- #
# MVR records (SFR -> LAK coupling seam; data, not an import edge).
# --------------------------------------------------------------------------- #


# A reach is coupled to a lake only when it is within this distance of a shoreline (a
# real feeder the DEM merely fell short on) and stays at least this far from the model
# outlet (else it is the below-dam DISCHARGE reach, which leaves the model -- the lake
# feeds it, not the reverse). These are DEFAULTS; each network overrides them through
# FlowReachNetworkConfig.lake_feeder_snap / outlet_keepout.
_DEFAULT_LAKE_FEEDER_SNAP_M = 300.0
_DEFAULT_OUTLET_KEEPOUT_M = 1000.0


def build_sfr_mover_records(
    networks: Mapping[str, ResolvedSfrNetwork],
    *,
    lake_cells_by_number: Mapping[int, Sequence[int]] | None = None,
    cell_centroids: np.ndarray | None = None,
    outlet_xy: tuple[float, float] | None = None,
) -> list[MoverRecord]:
    """Compile the ``outflow_to_lake`` couplings into general MVR transfers.

    EVERY terminal-to-lake reach of a coupled network provides its DOWNSTREAM-FLOW
    to the receiving lake (0-based lake number): a real reservoir is usually fed by
    several tributaries, each truncated at the shoreline, so one MVR record is
    emitted per terminal reach, routed to the SPECIFIC lake it drains into
    (``terminal_lake``), else ``outflow_to_lake``. A BARE outlet of a lake-coupled
    network (no downstream, no lake flag) is the main stem dead-ending short of the
    lake where the DEM's flat water body breaks its D8 path: it is handed to the
    NEAREST lake cell (needs ``lake_cells_by_number`` + ``cell_centroids``), so the
    principal river reaches its forebay instead of leaking out by EXT-OUTFLOW.
    """
    lake_points: list[tuple[int, int]] = []
    if lake_cells_by_number and cell_centroids is not None:
        for lake_num, cells in lake_cells_by_number.items():
            for cell2d in cells:
                lake_points.append((int(cell2d), int(lake_num)))
    lake_xy = (
        np.asarray([cell_centroids[c] for c, _ in lake_points], dtype=float)
        if lake_points
        else None
    )

    records: list[MoverRecord] = []
    for network_id, network in networks.items():
        definition = network.definition
        location = f"flow.sinks_sources.sfr.{network_id}"
        lake_number = definition.get("outflow_to_lake")
        flagged = any(record.is_terminal_to_lake for record in network.reaches)
        if not flagged and lake_number is None:
            # Standalone network: it discharges out of the model (EXT-OUTFLOW).
            continue
        terminals = _terminal_reaches(network, location=location)
        mvrtype = str(definition.get("outflow_mvrtype") or "FACTOR").strip().upper()
        raw_value = definition.get("outflow_value")
        value = float(raw_value) if raw_value is not None else 1.0
        _snap = definition.get("lake_feeder_snap")
        feeder_snap_m = _length_m(_snap) if _snap is not None else _DEFAULT_LAKE_FEEDER_SNAP_M
        _keepout = definition.get("outlet_keepout")
        outlet_keepout_m = (
            _length_m(_keepout) if _keepout is not None else _DEFAULT_OUTLET_KEEPOUT_M
        )

        # Bare outlets (no downstream, no lake flag) hand to the nearest lake cell.
        # Only when the network HAS flagged shoreline reaches: with none, the single
        # outlet is the terminal (handled below via outflow_to_lake), not a bare one.
        # A terminal (flagged OR bare) CLOSE to the model outlet is the below-dam
        # DISCHARGE reach (the lake feeds it and it leaves the model), not a feeder --
        # position, not elevation, since a deep-bathymetry feeder can be lower than the
        # discharge. Elevation is unreliable; the outlet distance separates them.
        def _near_outlet(
            cellid: tuple[int, int] | None, *, keepout_m: float = outlet_keepout_m
        ) -> bool:
            if outlet_xy is None or cellid is None or cell_centroids is None:
                return False
            here = cell_centroids[int(cellid[1])]
            return float(np.hypot(here[0] - outlet_xy[0], here[1] - outlet_xy[1])) < keepout_m

        if flagged and lake_xy is not None:
            unsnapped: list[tuple[int, float]] = []
            for reach in network.reaches:
                if reach.downstream or reach.is_terminal_to_lake or reach.cellid is None:
                    continue
                here = cell_centroids[int(reach.cellid[1])]
                d2 = ((lake_xy - here) ** 2).sum(axis=1)
                nearest = int(np.argmin(d2))
                # Skip a dead-end FAR from any shoreline (a main stem stopping at a flat
                # forebay): teleporting it would drop an entry "in the void". Collect it
                # instead of dropping it silently: its whole flow then leaves the model by
                # EXT-OUTFLOW, which starves the lake without any signal (a main stem
                # stopping short of the shoreline can carry most of the network
                # outflow out of the model).
                if float(d2[nearest]) ** 0.5 > feeder_snap_m:
                    unsnapped.append((int(reach.ifno), float(d2[nearest]) ** 0.5))
                    continue
                if _near_outlet(reach.cellid):
                    continue  # below-dam discharge reach, not a lake feeder
                records.append(
                    MoverRecord(
                        provider=_SFR_PACKAGE_NAME,
                        provider_id=int(reach.ifno),
                        receiver=_LAK_PACKAGE_NAME,
                        receiver_id=int(lake_points[nearest][1]),
                        mvrtype=mvrtype,
                        value=value,
                    )
                )
            if unsnapped:
                closest = min(unsnapped, key=lambda item: item[1])
                logger.warning(
                    "%s: %d dead-end reach(es) stop short of every shoreline and stay "
                    "unrouted, so their flow leaves the model by EXT-OUTFLOW instead of "
                    "feeding the lake (nearest is reach %d, %.0f m from the shore, for a "
                    "lake_feeder_snap of %.0f m). Carve the channel to the shore with "
                    "geographic.enforce_lakes.capture_radius_m, or raise lake_feeder_snap "
                    "above %.0f m to snap them.",
                    location,
                    len(unsnapped),
                    closest[0],
                    closest[1],
                    feeder_snap_m,
                    closest[1],
                )
        for terminal in terminals:
            if _near_outlet(terminal.cellid):
                continue  # below-dam discharge reach, the lake feeds it
            if terminal.terminal_lake is not None:
                receiver_lake = int(terminal.terminal_lake)
            elif lake_number is not None:
                receiver_lake = int(lake_number)
            else:
                # A terminal flagged as feeding a lake but with neither a lake tag
                # nor outflow_to_lake would leave the model by EXT-OUTFLOW (the
                # RC-1 failure mode). Warn and skip so it is surfaced, not silent.
                logger.warning(
                    "%s: terminal reach %d feeds a lake but no receiver is set (no lake tag, "
                    "no outflow_to_lake); its flow leaves the model by EXT-OUTFLOW. Set "
                    "outflow_to_lake to route it to the reservoir.",
                    location,
                    int(terminal.ifno),
                )
                continue
            records.append(
                MoverRecord(
                    provider=_SFR_PACKAGE_NAME,
                    provider_id=int(terminal.ifno),
                    receiver=_LAK_PACKAGE_NAME,
                    receiver_id=int(receiver_lake) - 1,
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
    has_mover_records: bool = False,
    solver_mesh: SolverMesh | None = None,
) -> dict[str, Any] | None:
    """Assemble the ``ModflowGwfsfr`` arguments for the active SFR network.

    Returns ``None`` when no network is active. The returned dict feeds
    ``flopy.mf6.ModflowGwfsfr`` plus side-channel keys popped in ``build.py``
    (``obs_continuous``, ``sfr_obs_meta``, ``ts_specs``).

    ``external_mover`` flags MVR records from OTHER packages targeting this SFR
    (a LAK spillway release or the routed hillslope drainage): the package then
    advertises MOVER and the obs spec requests the per-reach to/from-mvr series
    even with no SFR-owned mover record. ``has_mover_records`` flags SFR-owned
    mover records (already computed once in ``build.py``); the records
    themselves are routed there, so only the boolean is needed here.
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

    botm = None if solver_mesh is None else np.asarray(solver_mesh.botm, dtype=float)

    # Floor every reach's streambed top so its bed (rtp - rbth) stays above the cell
    # bottom, THEN restore the monotone-downhill order the network freeze set. The
    # floor comes from each cell's own botm, so a lake-enforced routing DEM can floor
    # a downstream reach UP past its upstream neighbour and re-break monotonicity; a
    # per-record clamp cannot see that. Re-sweep from the outlet up and lift each
    # upstream reach to sit above its (already floored) downstream one. Lifting never
    # re-sinks a bed below its cell, so the floor and the monotone order both hold.
    min_slope = float(definition.get("min_slope") or 1e-4)
    by_ifno = {record.ifno: record for record in reaches}
    rtp_by_ifno: dict[int, float] = {}
    for record in reaches:
        rtp_val = float(record.rtp)
        if record.cellid is not None and botm is not None:
            cell_bottom = float(botm[int(record.cellid[0]), int(record.cellid[1])])
            rtp_val = max(rtp_val, cell_bottom + float(rbth) + _RTP_ABOVE_BOTTOM_M)
        rtp_by_ifno[record.ifno] = rtp_val
    for record in reversed(reaches):
        down_rtp = rtp_by_ifno[record.ifno]
        for up in record.upstream:
            drop = min_slope * 0.5 * (float(by_ifno[up].rlen) + float(record.rlen))
            floor = down_rtp + drop
            if rtp_by_ifno[up] < floor:
                rtp_by_ifno[up] = floor

    packagedata: list[list[Any]] = []
    connectiondata: list[list[Any]] = []
    for record in reaches:
        ncon = len(record.upstream) + len(record.downstream)
        cellid = record.cellid if record.cellid is not None else _UNCONNECTED_CELLID
        rtp_val = rtp_by_ifno[record.ifno]
        packagedata.append(
            [
                int(record.ifno),
                (int(cellid[0]), int(cellid[1])),
                float(record.rlen),
                float(record.rwid),
                float(record.rgrd),
                float(rtp_val),
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

    time_conversion, length_conversion = package_unit_conversions(model)
    stem = _sfr_output_stem(model)
    obs_continuous, sfr_obs_meta = build_sfr_obs_spec(
        stem=stem, network=network, has_mover=has_mover_records or external_mover
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
    if has_mover_records or external_mover:
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
    "watershed_drainage_cell_mask",
]
