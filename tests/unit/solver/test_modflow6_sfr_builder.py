"""Unit tests for the MF6 SFR package builder (DISV, order-preserving split)."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest
from shapely.geometry import LineString, box

from hydromodpy.physics.flow.sinks_sources.sfr import (
    FlowReachConfig,
    FlowReachNetworkConfig,
)
from hydromodpy.solver.modflow6.builders.mvr import MoverRecord
from hydromodpy.solver.modflow6.builders.sfr import (
    ResolvedSfrNetwork,
    SfrReachRecord,
    build_drainage_mover_records,
    build_sfr_mover_records,
    build_sfr_obs_spec,
    build_sfr_package_args,
    build_sfr_period_data,
    remove_drain_cells,
    resolve_sfr_networks,
    sfr_drain_cells_to_drop,
    watershed_drainage_cell_mask,
)
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh
from hydromodpy.spatial.geographic.core.sfr_network import SfrReachRow, SfrReachTrace


def _mesh(nrow: int = 5, ncol: int = 5, nlay: int = 1) -> SolverMesh:
    top = np.full((nrow, ncol), 100.0)
    botm = np.stack([np.full((nrow, ncol), 100.0 - 50.0 * (k + 1)) for k in range(nlay)])
    return SolverMesh.from_structured_arrays(
        nrow=nrow, ncol=ncol, top=top, botm=botm, dx=10.0, dy=10.0
    )


def _reach_row(
    ifno: int,
    line: LineString,
    *,
    rtp: float,
    rgrd: float = 1e-3,
    strahler: int = 1,
    area_km2: float = 1.0,
    upstream: tuple[int, ...] = (),
    downstream: tuple[int, ...] = (),
    terminal: bool = False,
    terminal_lake: int | None = None,
) -> SfrReachRow:
    return SfrReachRow(
        ifno=ifno,
        line=line,
        rlen=float(line.length),
        rtp=rtp,
        rgrd=rgrd,
        strahler=strahler,
        area_km2=area_km2,
        upstream=upstream,
        downstream=downstream,
        is_terminal_to_lake=terminal,
        terminal_lake=terminal_lake,
    )


def _fake_model(payloads: dict, nper: int = 1, perlen: tuple[float, ...] = (86400.0,)):
    return SimpleNamespace(
        flow=SimpleNamespace(active_bc=["sfr"], sinks_sources={"sfr": payloads}),
        nper=nper,
        perlen=np.asarray(perlen, dtype=float),
        steady=(False,) * nper,
        time_grid=None,
        time_units="seconds",
        model_output_name="sfrtest",
    )


def _trace_payload(trace: SfrReachTrace, **overrides) -> dict:
    payload = {
        "width": {"kind": "constant", "value": 2.0},
        "reach_trace": trace,
    }
    payload.update(overrides)
    return payload


def _two_reach_trace() -> SfrReachTrace:
    # Reach 0 (headwater) runs diagonally across several cells, reach 1 continues
    # to the grid edge and is flagged terminal-to-lake.
    head = LineString([(2.0, 48.0), (25.0, 25.0)])
    tail = LineString([(25.0, 25.0), (48.0, 3.0)])
    rows = (
        _reach_row(0, head, rtp=95.0, downstream=(1,)),
        _reach_row(1, tail, rtp=94.0, upstream=(0,), terminal=True),
    )
    return SfrReachTrace(reaches=rows, crs_wkt="EPSG:32630")


def test_trace_split_is_ordered_and_downstream_increasing() -> None:
    mesh = _mesh()
    model = _fake_model({"net0": _trace_payload(_two_reach_trace())})
    networks = resolve_sfr_networks(model, solver_mesh=mesh)
    network = networks["net0"]
    reaches = network.reaches

    # The two diagonal lines cross several cells each: the split happened.
    assert len(reaches) > 2
    assert [reach.ifno for reach in reaches] == list(range(len(reaches)))
    assert network.downstream_increasing
    # Reciprocity holds on the final ids.
    by_ifno = {reach.ifno: reach for reach in reaches}
    for reach in reaches:
        for down in reach.downstream:
            assert reach.ifno in by_ifno[down].upstream

    # The split conserves the polyline length.
    total = sum(reach.rlen for reach in reaches)
    expected = sum(row.line.length for row in _two_reach_trace().reaches)
    assert total == pytest.approx(expected, rel=1e-6)

    # Headwater / terminal flags land on the first / last reach.
    assert by_ifno[0].is_headwater
    assert by_ifno[len(reaches) - 1].is_terminal_to_lake
    assert not by_ifno[len(reaches) - 1].downstream

    # Streambed tops descend monotonically along every connection.
    for reach in reaches:
        for down in reach.downstream:
            assert by_ifno[down].rtp < reach.rtp

    # Every reach sits on an active aquifer cell of the single layer.
    assert all(reach.cellid is not None and reach.cellid[0] == 0 for reach in reaches)


def test_trace_split_assigns_cells_in_along_line_order() -> None:
    mesh = _mesh()
    line = LineString([(5.0, 45.0), (45.0, 45.0)])  # straight west-east in top row
    trace = SfrReachTrace(reaches=(_reach_row(0, line, rtp=95.0),), crs_wkt="")
    model = _fake_model({"net0": _trace_payload(trace)})
    networks = resolve_sfr_networks(model, solver_mesh=mesh)
    cells = [reach.cellid[1] for reach in networks["net0"].reaches]
    # from_structured_arrays builds row-major cells with y increasing upward, so
    # the top row (y in [40, 50]) is cells 40..44 west to east.
    assert cells == sorted(cells)
    assert len(cells) == 4 or len(cells) == 5


def test_unconnected_network_uses_unconnected_cellid() -> None:
    mesh = _mesh()
    model = _fake_model({"net0": _trace_payload(_two_reach_trace(), connected_to_aquifer=False)})
    networks = resolve_sfr_networks(model, solver_mesh=mesh)
    assert all(reach.cellid is None for reach in networks["net0"].reaches)
    args = build_sfr_package_args(model, networks=networks)
    assert all(row[1] == (-1, -1) for row in args["packagedata"])


def test_packagedata_layout_and_connection_signs() -> None:
    mesh = _mesh()
    model = _fake_model({"net0": _trace_payload(_two_reach_trace())})
    networks = resolve_sfr_networks(model, solver_mesh=mesh)
    args = build_sfr_package_args(model, networks=networks)

    assert args["nreaches"] == len(networks["net0"].reaches)
    assert args["maximum_picard_iterations"] == 1
    assert args["time_conversion"] == 1.0
    assert args["length_conversion"] == 1.0
    for row in args["packagedata"]:
        # [ifno, cellid, rlen, rwid, rgrd, rtp, rbth, rhk, man, ncon, ustrf, ndv]
        assert len(row) == 12
        assert isinstance(row[1], tuple) and len(row[1]) == 2
        assert row[2] > 0.0 and row[3] > 0.0 and row[4] > 0.0
        assert row[6] > 0.0  # rbth
        assert row[8] > 0.0  # manning
        assert row[10] == pytest.approx(1.0)  # ustrf
        assert row[11] == 0  # ndv

    by_ifno = {reach.ifno: reach for reach in networks["net0"].reaches}
    for row in args["connectiondata"]:
        ifno = row[0]
        ups = [c for c in row[1:] if c >= 0]
        downs = [-c for c in row[1:] if c < 0]
        assert tuple(sorted(ups)) == by_ifno[ifno].upstream
        assert tuple(sorted(downs)) == by_ifno[ifno].downstream


def test_width_laws_resolve_per_reach() -> None:
    mesh = _mesh()
    line = LineString([(5.0, 45.0), (45.0, 45.0)])
    trace = SfrReachTrace(
        reaches=(_reach_row(0, line, rtp=95.0, strahler=2, area_km2=4.0),), crs_wkt=""
    )

    def widths_for(width_cfg: dict) -> list[float]:
        model = _fake_model({"net0": _trace_payload(trace, width=width_cfg)})
        networks = resolve_sfr_networks(model, solver_mesh=mesh)
        return [reach.rwid for reach in networks["net0"].reaches]

    assert all(w == pytest.approx(3.5) for w in widths_for({"kind": "constant", "value": 3.5}))
    assert all(
        w == pytest.approx(2.5)
        for w in widths_for({"kind": "by_order", "widths": {1: 1.0, 2: 2.5}})
    )
    # Order 3 is undeclared: clamp to the widest declared order below.
    assert all(
        w == pytest.approx(2.5)
        for w in widths_for({"kind": "by_order", "widths": {1: 1.0, 2: 2.5}})
    )
    assert all(
        w == pytest.approx(2.0 * 4.0**0.5)
        for w in widths_for({"kind": "power_law", "coef": 2.0, "exp": 0.5})
    )


def _explicit_payload(reaches: list[FlowReachConfig], **overrides) -> FlowReachNetworkConfig:
    return FlowReachNetworkConfig(reaches=reaches, **overrides)


def _chain_reach(row: int, col: int, upstream: list[int], downstream: list[int], top: float):
    return FlowReachConfig(
        cell={"kind": "cell", "cell": [0, row, col]},
        length="10 m",
        width="2 m",
        slope=1e-3,
        top=top,
        upstream=upstream,
        downstream=downstream,
    )


def test_explicit_network_resolves_cells_and_runs_picard_check() -> None:
    mesh = _mesh()
    payload = _explicit_payload(
        [
            _chain_reach(0, 1, [], [2], 96.0),
            _chain_reach(1, 1, [1], [3], 95.9),
            _chain_reach(2, 1, [2], [], 95.8),
        ]
    )
    model = _fake_model({"net0": payload})
    networks = resolve_sfr_networks(model, solver_mesh=mesh)
    reaches = networks["net0"].reaches
    assert [reach.cellid for reach in reaches] == [(0, 1), (0, 6), (0, 11)]
    assert networks["net0"].downstream_increasing
    args = build_sfr_package_args(model, networks=networks)
    assert args["maximum_picard_iterations"] == 1


def test_explicit_network_downstream_to_first_reach_raises() -> None:
    mesh = _mesh()
    payload = _explicit_payload(
        [
            _chain_reach(0, 1, [2], [], 95.8),
            _chain_reach(1, 1, [], [1], 96.0),
        ]
    )
    model = _fake_model({"net0": payload})
    with pytest.raises(ValueError, match="downstream"):
        resolve_sfr_networks(model, solver_mesh=mesh)


def test_explicit_network_non_reciprocal_raises() -> None:
    mesh = _mesh()
    payload = _explicit_payload(
        [
            _chain_reach(0, 1, [], [2], 96.0),
            _chain_reach(1, 1, [], [], 95.9),  # missing upstream=[1]
        ]
    )
    model = _fake_model({"net0": payload})
    with pytest.raises(ValueError, match="reciprocal"):
        resolve_sfr_networks(model, solver_mesh=mesh)


def test_explicit_network_ustrf_siblings_must_sum_to_one() -> None:
    mesh = _mesh()
    fork = _chain_reach(0, 1, [], [2, 3], 96.0)
    left = FlowReachConfig(
        cell={"kind": "cell", "cell": [0, 1, 0]},
        length="10 m",
        width="2 m",
        slope=1e-3,
        top=95.9,
        upstream=[1],
        downstream=[],
        ustrf=0.6,
    )
    right = FlowReachConfig(
        cell={"kind": "cell", "cell": [0, 1, 2]},
        length="10 m",
        width="2 m",
        slope=1e-3,
        top=95.9,
        upstream=[1],
        downstream=[],
        ustrf=0.6,
    )
    model = _fake_model({"net0": _explicit_payload([fork, left, right])})
    with pytest.raises(ValueError, match="ustrf"):
        resolve_sfr_networks(model, solver_mesh=mesh)


def test_period_data_distributes_runoff_by_length_and_inflow_on_headwater() -> None:
    mesh = _mesh()
    model = _fake_model(
        {
            "net0": _trace_payload(
                _two_reach_trace(),
                headwater_inflow={"kind": "constant", "value": 0.05, "units": "m3/s"},
                runoff={"kind": "constant", "value": 0.02, "units": "m3/s"},
                rainfall={"kind": "constant", "value": 1e-8, "units": "m/s"},
            )
        }
    )
    networks = resolve_sfr_networks(model, solver_mesh=mesh)
    network = networks["net0"]
    rows, ts_series = build_sfr_period_data(model, network=network)
    assert ts_series == []
    period0 = rows[0]

    inflow_rows = [row for row in period0 if row[1] == "inflow"]
    assert len(inflow_rows) == 1
    assert inflow_rows[0][0] == 0  # the headwater reach
    assert inflow_rows[0][2] == pytest.approx(0.05)

    runoff_rows = {row[0]: row[2] for row in period0 if row[1] == "runoff"}
    assert set(runoff_rows) == {reach.ifno for reach in network.reaches}
    assert sum(runoff_rows.values()) == pytest.approx(0.02)
    total_length = sum(reach.rlen for reach in network.reaches)
    for reach in network.reaches:
        assert runoff_rows[reach.ifno] == pytest.approx(0.02 * reach.rlen / total_length)

    rainfall_rows = [row for row in period0 if row[1] == "rainfall"]
    assert len(rainfall_rows) == len(network.reaches)
    assert all(row[2] == pytest.approx(1e-8) for row in rainfall_rows)


def test_drain_deconfliction_drops_reach_cells() -> None:
    mesh = _mesh()
    model = _fake_model({"net0": _trace_payload(_two_reach_trace())})
    networks = resolve_sfr_networks(model, solver_mesh=mesh)
    cells = sfr_drain_cells_to_drop(networks)
    assert cells  # the de-confliction set is non-empty
    drn_spd = {0: [[0, cid, 100.0, 0.05] for cid in range(25)]}
    filtered = remove_drain_cells(drn_spd, cells=cells)
    remaining = {int(row[1]) for row in filtered[0]}
    assert remaining == set(range(25)) - cells


def test_trace_reach_is_truncated_at_a_lake_cell() -> None:
    # Once the DEM is hydro-conditioned, a stream routes THROUGH a lake; the reach
    # must be cut at the lake footprint (no reach on a LAK cell) and the last dry
    # reach flagged terminal-to-lake, tagged with that lake.
    mesh = _mesh()
    line = LineString([(5.0, 45.0), (45.0, 45.0)])  # straight west-east, top row
    trace = SfrReachTrace(reaches=(_reach_row(0, line, rtp=95.0),), crs_wkt="")
    model = _fake_model({"net0": _trace_payload(trace, outflow_to_lake=1)})
    base = [r.cellid[1] for r in resolve_sfr_networks(model, solver_mesh=mesh)["net0"].reaches]
    lake_cell = base[-1]  # the downstream-most cell becomes a lake cell
    trunc = resolve_sfr_networks(model, solver_mesh=mesh, lake_cells_by_number={0: [lake_cell]})
    cells = [r.cellid[1] for r in trunc["net0"].reaches if r.cellid is not None]
    assert lake_cell not in cells  # no reach sits on the lake cell
    assert len(cells) == len(base) - 1
    terminals = [r for r in trunc["net0"].reaches if r.is_terminal_to_lake]
    assert len(terminals) == 1
    assert terminals[0].cellid[1] == base[-2]  # the last dry cell is the shoreline
    assert terminals[0].terminal_lake == 1  # 0-based lake 0 -> 1-based tag


def test_bare_outlet_routes_to_the_nearest_lake_cell() -> None:
    # A lake-coupled network with a flagged shoreline tributary PLUS an unflagged bare
    # outlet (the main stem dead-ending short of the flat forebay): the bare outlet
    # hands its flow to the NEAREST lake cell, not EXT-OUTFLOW nor the far fallback.
    flagged = SfrReachRecord(
        ifno=0,
        cellid=(0, 0),
        rlen=10.0,
        rwid=1.0,
        rgrd=0.01,
        rtp=95.0,
        upstream=(),
        downstream=(),
        is_terminal_to_lake=True,
        terminal_lake=1,
    )
    bare = SfrReachRecord(
        ifno=1,
        cellid=(0, 5),
        rlen=10.0,
        rwid=1.0,
        rgrd=0.01,
        rtp=95.0,
        upstream=(),
        downstream=(),
        is_terminal_to_lake=False,
    )
    network = ResolvedSfrNetwork(
        network_id="net0", reaches=(flagged, bare), definition={"outflow_to_lake": 1}
    )
    cell_centroids = np.zeros((11, 2), dtype=float)
    cell_centroids[5] = (5.0, 0.0)  # the bare outlet reach
    cell_centroids[6] = (6.0, 0.0)  # lake 1 cell (near the bare outlet)
    cell_centroids[10] = (100.0, 0.0)  # lake 0 cell (far)
    records = build_sfr_mover_records(
        {"net0": network},
        lake_cells_by_number={0: [10], 1: [6]},
        cell_centroids=cell_centroids,
    )
    by_provider = {r.provider_id: r for r in records}
    assert by_provider[0].receiver_id == 0  # flagged terminal_lake=1 -> 0-based lake 0
    assert by_provider[1].receiver == "LAK"
    assert by_provider[1].receiver_id == 1  # bare outlet -> nearest lake cell 6 = lake 1


def _flagged_plus_bare(bare_xy: tuple[float, float]) -> tuple[dict, np.ndarray]:
    flagged = SfrReachRecord(
        ifno=0,
        cellid=(0, 0),
        rlen=10.0,
        rwid=1.0,
        rgrd=0.01,
        rtp=95.0,
        upstream=(),
        downstream=(),
        is_terminal_to_lake=True,
        terminal_lake=1,
    )
    bare = SfrReachRecord(
        ifno=1,
        cellid=(0, 5),
        rlen=10.0,
        rwid=1.0,
        rgrd=0.01,
        rtp=95.0,
        upstream=(),
        downstream=(),
        is_terminal_to_lake=False,
    )
    network = ResolvedSfrNetwork(
        network_id="net0", reaches=(flagged, bare), definition={"outflow_to_lake": 1}
    )
    cc = np.zeros((11, 2), dtype=float)
    cc[5] = bare_xy
    cc[6] = (0.0, 0.0)  # lake 1 cell at the origin
    cc[10] = (10_000.0, 0.0)  # lake 0 cell far away
    return {"net0": network}, cc


def test_bare_outlet_far_from_any_shoreline_is_not_teleported() -> None:
    # A dead-end 400 m from the nearest lake cell (> the 300 m feeder snap) is not a
    # feeder the DEM fell short on; teleporting it would drop an entry "in the void".
    nets, cc = _flagged_plus_bare((400.0, 0.0))
    records = build_sfr_mover_records(
        nets, lake_cells_by_number={0: [10], 1: [6]}, cell_centroids=cc
    )
    assert all(r.provider_id != 1 for r in records)  # the bare outlet leaves the model


def test_bare_outlet_near_the_model_outlet_is_not_teleported() -> None:
    # A dead-end 50 m from a lake but right at the model outlet is the below-dam
    # DISCHARGE reach; it leaves the model (the lake feeds it), never fed to the lake.
    nets, cc = _flagged_plus_bare((50.0, 0.0))
    records = build_sfr_mover_records(
        nets,
        lake_cells_by_number={0: [10], 1: [6]},
        cell_centroids=cc,
        outlet_xy=(60.0, 0.0),  # 10 m from the reach, well inside the 1000 m keepout
    )
    assert all(r.provider_id != 1 for r in records)


def test_flagged_terminal_near_the_outlet_is_not_fed() -> None:
    # A flagged shoreline terminal sitting at the model outlet is the below-dam
    # DISCHARGE reach (the notch outflow reaching back into the footprint); it leaves
    # the model, never fed to the lake -- regardless of its streambed elevation.
    near_outlet = SfrReachRecord(
        ifno=0,
        cellid=(0, 0),
        rlen=10.0,
        rwid=1.0,
        rgrd=0.01,
        rtp=95.0,
        upstream=(),
        downstream=(),
        is_terminal_to_lake=True,
        terminal_lake=1,
    )
    network = ResolvedSfrNetwork(
        network_id="net0", reaches=(near_outlet,), definition={"outflow_to_lake": 1}
    )
    cc = np.zeros((2, 2), dtype=float)
    cc[0] = (0.0, 0.0)
    records = build_sfr_mover_records(
        {"net0": network},
        lake_cells_by_number={0: [1]},
        cell_centroids=cc,
        outlet_xy=(5.0, 0.0),  # 5 m from the terminal, well inside the keepout
    )
    assert all(r.provider_id != 0 for r in records)


def test_deep_feeder_far_from_outlet_is_fed() -> None:
    # A shoreline feeder entering the reservoir at a LOW streambed (deep bathymetry) is
    # still coupled: elevation is not the discriminator, distance to the outlet is. Far
    # from the outlet -> a real feeder, fed to the lake.
    feeder = SfrReachRecord(
        ifno=0,
        cellid=(0, 0),
        rlen=10.0,
        rwid=1.0,
        rgrd=0.01,
        rtp=58.0,  # deep bed
        upstream=(),
        downstream=(),
        is_terminal_to_lake=True,
        terminal_lake=1,
    )
    network = ResolvedSfrNetwork(
        network_id="net0", reaches=(feeder,), definition={"outflow_to_lake": 1}
    )
    cc = np.zeros((2, 2), dtype=float)
    cc[0] = (0.0, 0.0)
    records = build_sfr_mover_records(
        {"net0": network},
        lake_cells_by_number={0: [1]},
        cell_centroids=cc,
        outlet_xy=(5000.0, 0.0),  # far from the outlet
    )
    assert any(r.provider_id == 0 and r.receiver == "LAK" for r in records)


def test_mover_records_couple_terminal_reach_to_lake() -> None:
    mesh = _mesh()
    model = _fake_model(
        {"net0": _trace_payload(_two_reach_trace(), outflow_to_lake=1, outflow_value=1.0)}
    )
    networks = resolve_sfr_networks(model, solver_mesh=mesh)
    records = build_sfr_mover_records(networks)
    assert len(records) == 1
    record = records[0]
    assert isinstance(record, MoverRecord)
    assert record.provider == "SFR"
    assert record.receiver == "LAK"
    assert record.receiver_id == 0
    terminal = max(reach.ifno for reach in networks["net0"].reaches)
    assert record.provider_id == terminal
    # The coupled build advertises MOVER (the records themselves are routed in
    # build.py; the package only needs the has_mover_records flag).
    args = build_sfr_package_args(model, networks=networks, has_mover_records=bool(records))
    assert args["mover"] is True


def _two_terminal_two_lake_trace() -> SfrReachTrace:
    # Two independent streams: the west one drains into lake 2 (the pre-retenue),
    # the east one into lake 1 (the main reservoir). Each terminal carries its own
    # lake tag.
    west = LineString([(5.0, 45.0), (20.0, 45.0)])
    east = LineString([(30.0, 45.0), (45.0, 45.0)])
    rows = (
        _reach_row(0, west, rtp=95.0, terminal=True, terminal_lake=2),
        _reach_row(1, east, rtp=95.0, terminal=True, terminal_lake=1),
    )
    return SfrReachTrace(reaches=rows, crs_wkt="EPSG:32630")


def test_mover_records_route_each_terminal_to_its_tagged_lake() -> None:
    # outflow_to_lake = 1 is only the fallback: each terminal routes to the
    # specific lake it drains into (terminal_lake), so the two terminals reach
    # lakes 1 and 2 (receiver_id 0 and 1), not both lake 1.
    mesh = _mesh()
    model = _fake_model({"net0": _trace_payload(_two_terminal_two_lake_trace(), outflow_to_lake=1)})
    networks = resolve_sfr_networks(model, solver_mesh=mesh)
    records = build_sfr_mover_records(networks)
    assert len(records) == 2
    assert all(r.receiver == "LAK" for r in records)
    assert sorted(r.receiver_id for r in records) == [0, 1]


def test_obs_spec_covers_each_reach_and_mover_terms() -> None:
    mesh = _mesh()
    model = _fake_model({"net0": _trace_payload(_two_reach_trace(), outflow_to_lake=1)})
    networks = resolve_sfr_networks(model, solver_mesh=mesh)
    network = networks["net0"]
    obs_continuous, meta = build_sfr_obs_spec(stem="m", network=network, has_mover=True)
    obslist = obs_continuous["m.sfr.obs.csv"]
    names = {entry[0] for entry in obslist}
    n = len(network.reaches)
    for reach in network.reaches:
        for quantity in ("stage", "depth", "downstream_flow", "ext_inflow", "ext_outflow"):
            assert f"r{reach.ifno}_{quantity}" in names
        assert f"r{reach.ifno}_gw_exchange" in names
        assert f"r{reach.ifno}_to_mvr" in names
    assert meta["reach_count"] == n
    assert meta["obs_csv"] == "m.sfr.obs.csv"
    assert all(entry["network_id"] == "net0" for entry in meta["entries"])
    # 0-based integer ids only (flopy chokes on boundname obs ids).
    assert all(isinstance(entry[2], tuple) and isinstance(entry[2][0], int) for entry in obslist)


def test_multiple_networks_are_rejected() -> None:
    mesh = _mesh()
    model = _fake_model(
        {
            "a": _trace_payload(_two_reach_trace()),
            "b": _trace_payload(_two_reach_trace()),
        }
    )
    networks = resolve_sfr_networks(model, solver_mesh=mesh)
    with pytest.raises(ValueError, match="one SFR network"):
        build_sfr_package_args(model, networks=networks)


def test_inactive_sfr_returns_no_network() -> None:
    mesh = _mesh()
    model = _fake_model({"net0": _trace_payload(_two_reach_trace())})
    model.flow.active_bc = ["drainage"]
    assert resolve_sfr_networks(model, solver_mesh=mesh) == {}
    assert build_sfr_package_args(model, networks={}) is None


def test_drainage_mover_records_route_each_drn_cell_to_its_nearest_reach() -> None:
    mesh = _mesh()
    model = _fake_model(
        {"net0": _trace_payload(_two_reach_trace(), route_drainage=True, outflow_to_lake=1)}
    )
    networks = resolve_sfr_networks(model, solver_mesh=mesh)
    reach_cells = {reach.cellid[1] for reach in networks["net0"].reaches}
    drn_spd = remove_drain_cells(
        {0: [[0, cid, 100.0, 0.05] for cid in range(25)]}, cells=reach_cells
    )
    records = build_drainage_mover_records(
        networks, drn_spd=drn_spd, cell_centroids=mesh.cell_centroids()
    )
    assert len(records) == len(drn_spd[0])
    by_ifno = {reach.ifno: reach for reach in networks["net0"].reaches}
    centroids = mesh.cell_centroids()
    for boundary_index, record in enumerate(records):
        assert record.provider == "DRN"
        assert record.provider_id == boundary_index
        assert record.receiver == "SFR"
        assert record.mvrtype == "FACTOR" and record.value == 1.0
        # The receiver really is the nearest reach cell.
        drn_xy = centroids[int(drn_spd[0][boundary_index][1])]
        best = min(
            by_ifno.values(),
            key=lambda reach: float(((centroids[reach.cellid[1]] - drn_xy) ** 2).sum()),
        )
        assert record.receiver_id == best.ifno


def test_drainage_mover_records_require_a_static_single_period_drn() -> None:
    mesh = _mesh()
    model = _fake_model({"net0": _trace_payload(_two_reach_trace(), route_drainage=True)})
    networks = resolve_sfr_networks(model, solver_mesh=mesh)
    rows = [[0, 0, 100.0, 0.05]]
    with pytest.raises(ValueError, match="single-period"):
        build_drainage_mover_records(
            networks, drn_spd={0: rows, 1: rows}, cell_centroids=mesh.cell_centroids()
        )


def test_drainage_mover_records_are_empty_without_the_opt_in() -> None:
    mesh = _mesh()
    model = _fake_model({"net0": _trace_payload(_two_reach_trace())})
    networks = resolve_sfr_networks(model, solver_mesh=mesh)
    records = build_drainage_mover_records(
        networks, drn_spd={0: [[0, 0, 100.0, 0.05]]}, cell_centroids=mesh.cell_centroids()
    )
    assert records == []


def test_drainage_near_the_lake_routes_directly_to_the_lake() -> None:
    # A lakeside DRN cell has no local reach (the network is truncated at the
    # shoreline). It hands its drainage DIRECTLY to the nearest lake cell (a real
    # DRN -> LAK mover), not through a distant terminal-reach proxy: the nearest
    # target wins. A drain on the trace path still routes to its nearest reach.
    mesh = _mesh()
    model = _fake_model(
        {"net0": _trace_payload(_two_reach_trace(), route_drainage=True, outflow_to_lake=1)}
    )
    networks = resolve_sfr_networks(model, solver_mesh=mesh)
    # The lake occupies the north-east corner cell, away from the diagonal trace;
    # the neighbouring drain is closer to the lake than to any reach.
    lake_cells = [24]
    drn_spd = {
        0: [
            [0, 23, 100.0, 0.05],  # lakeside -> DRN -> LAK (nearest lake cell)
            [0, 4, 100.0, 0.05],  # on the trace path -> nearest reach
        ]
    }
    records = build_drainage_mover_records(
        networks,
        drn_spd=drn_spd,
        cell_centroids=mesh.cell_centroids(),
        lake_cells_by_number={0: lake_cells},
    )
    assert [r.receiver for r in records] == ["LAK", "SFR"]
    assert records[0].receiver_id == 0  # outflow_to_lake=1 -> 0-based lake number 0


def test_drainage_mover_records_skip_buffer_cells_outside_the_watershed() -> None:
    # Buffer DRN cells (outside the watershed) model neighbouring basins: their
    # discharge must leave the model as a plain DRN, so they get NO mover record,
    # while the surviving providers keep their period-0 row index (no renumber).
    mesh = _mesh()
    model = _fake_model(
        {"net0": _trace_payload(_two_reach_trace(), route_drainage=True, outflow_to_lake=1)}
    )
    networks = resolve_sfr_networks(model, solver_mesh=mesh)
    reach_cells = {reach.cellid[1] for reach in networks["net0"].reaches}
    drn_spd = remove_drain_cells(
        {0: [[0, cid, 100.0, 0.05] for cid in range(25)]}, cells=reach_cells
    )
    # Mark the last two grid rows (cell2d >= 15) as buffer, outside the watershed.
    watershed_mask = np.array([cid < 15 for cid in range(mesh.n_cells)], dtype=bool)

    records = build_drainage_mover_records(
        networks,
        drn_spd=drn_spd,
        cell_centroids=mesh.cell_centroids(),
        watershed_cell_mask=watershed_mask,
    )

    rows = drn_spd[0]
    inside_indices = [i for i, row in enumerate(rows) if watershed_mask[int(row[1])]]
    outside_indices = [i for i, row in enumerate(rows) if not watershed_mask[int(row[1])]]
    assert outside_indices, "the fixture must include buffer DRN cells to exercise the skip"
    # One record per in-watershed DRN cell; provider ids are exactly the in-watershed
    # row positions (buffer rows dropped in place, not renumbered).
    assert [r.provider_id for r in records] == inside_indices
    assert all(watershed_mask[int(rows[r.provider_id][1])] for r in records)
    # No buffer cell is routed to any surface water.
    assert not (set(r.provider_id for r in records) & set(outside_indices))


def test_watershed_drainage_cell_mask_classifies_cells_by_centroid() -> None:
    mesh = _mesh()
    centroids = mesh.cell_centroids()
    xs = np.unique(centroids[:, 0])
    threshold = float((xs[2] + xs[3]) / 2.0)  # strictly between two cell columns
    poly = box(
        float(centroids[:, 0].min() - 1.0),
        float(centroids[:, 1].min() - 1.0),
        threshold,
        float(centroids[:, 1].max() + 1.0),
    )

    mask = watershed_drainage_cell_mask(poly, centroids)

    assert mask.dtype == bool and mask.shape == (mesh.n_cells,)
    assert np.array_equal(mask, centroids[:, 0] < threshold)
    assert mask.any() and not mask.all()  # genuinely partitions the grid
