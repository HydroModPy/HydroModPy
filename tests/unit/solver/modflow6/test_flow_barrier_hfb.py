"""Build MODFLOW 6 HFB rows from a barrier line carved to a depth."""

from __future__ import annotations

import logging
from types import SimpleNamespace

import numpy as np
import pytest
from shapely.geometry import LineString

from hydromodpy.model.boundaries.barriers import apply_flow_barriers_to_flow
from hydromodpy.model.boundaries.lakes import apply_cutoff_wall_to_flow
from hydromodpy.model.sinks_sources.flow_barrier import FlowBarrierConfig
from hydromodpy.model.sinks_sources.lake import FlowLakeConfig
from hydromodpy.solver.modflow6.builders.flow_barrier import (
    build_flow_barrier_hfb,
    resolve_flow_barrier_hfb_rows,
)
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh
from hydromodpy.spatial.mesh.model.cell_types import CellType
from hydromodpy.spatial.mesh.model.hydro_mesh import CellBlock, HydroMesh
from tests._helpers.solver_meshes import solver_mesh_from

# A near-vertical trace across the 2x2 grid: it separates the left column from the
# right one at both rows, so it bars the connected faces (0, 1) and (2, 3).
_CUT = LineString([(1.01, -0.5), (1.01, 2.5)])


def _two_layer_grid() -> SolverMesh:
    # 2x2 unit quads (cells c0=(0,0), c1=(1,0), c2=(0,1), c3=(1,1)); top = 10, two 5 m layers.
    verts = np.array([[i, j] for j in range(3) for i in range(3)], dtype=float)

    def v(i: int, j: int) -> int:
        return j * 3 + i

    conn = np.array(
        [[v(i, j), v(i + 1, j), v(i + 1, j + 1), v(i, j + 1)] for j in range(2) for i in range(2)],
        dtype=int,
    )
    mesh = HydroMesh(vertices=verts, cell_blocks=(CellBlock(CellType.QUADRILATERAL, conn),))
    return solver_mesh_from(
        mesh,
        top=np.full(4, 10.0),
        botm=np.array([[5.0] * 4, [0.0] * 4]),
        inactive_mask=np.zeros((2, 4), dtype=bool),
    )


def test_shallow_depth_spans_top_layer_only() -> None:
    sm = _two_layer_grid()
    rows = build_flow_barrier_hfb(sm, line=_CUT, depths=[4.0], hydchr=1e-9)
    assert sorted({r[0][0] for r in rows}) == [0]
    assert sorted({(r[0][1], r[1][1]) for r in rows}) == [(0, 1), (2, 3)]


def test_deep_depth_spans_both_layers() -> None:
    sm = _two_layer_grid()
    rows = build_flow_barrier_hfb(sm, line=_CUT, depths=[8.0], hydchr=1e-9)
    assert sorted({r[0][0] for r in rows}) == [0, 1]
    assert len(rows) == 4
    assert all(r[2] == 1e-9 for r in rows)


def test_crest_elevation_bars_below_the_top() -> None:
    # A grout curtain whose crest sits below the model top: crest 4 m, depth 3 m
    # -> the barrier spans [1, 4] m, which skips the top layer (5-10 m) entirely
    # and bars only the deep layer (0-5 m).
    sm = _two_layer_grid()
    rows = build_flow_barrier_hfb(sm, line=_CUT, depths=[3.0], hydchr=1e-9, crest_elevation=4.0)
    assert sorted({r[0][0] for r in rows}) == [1]
    assert sorted({(r[0][1], r[1][1]) for r in rows}) == [(0, 1), (2, 3)]


def test_base_elevation_bars_the_full_column() -> None:
    # A full-height impervious dam: floor at 1 m, crest at the cell top (10 m) -> the
    # barrier spans [1, 10] and bars BOTH layers, so nothing flows over the wall.
    sm = _two_layer_grid()
    rows = build_flow_barrier_hfb(sm, line=_CUT, hydchr=1e-9, base_elevation=1.0)
    assert sorted({r[0][0] for r in rows}) == [0, 1]
    assert len(rows) == 4


def test_per_segment_depth_is_interpolated_along_the_line() -> None:
    sm = _two_layer_grid()
    # shallow (4 m) at the start (bottom), deep (7 m) at the end (top) of the trace.
    rows = build_flow_barrier_hfb(sm, line=_CUT, depths=[4.0, 7.0], hydchr=1e-9)
    by_face: dict[tuple[int, int], list[int]] = {}
    for r in rows:
        by_face.setdefault((r[0][1], r[1][1]), []).append(r[0][0])
    # the shallow end stays in the top layer, the deeper end reaches the bottom layer
    assert by_face[(0, 1)] == [0]
    assert sorted(by_face[(2, 3)]) == [0, 1]


def _stepped_two_cells() -> SolverMesh:
    # Two side-by-side quads; cell 0 is elevated (aquifer 10-20 m), cell 1 is low
    # (aquifer 0-10 m), so an absolute band below 10 m misses cell 0's aquifer.
    verts = np.array([[0, 0], [1, 0], [2, 0], [0, 1], [1, 1], [2, 1]], dtype=float)
    conn = np.array([[0, 1, 4, 3], [1, 2, 5, 4]], dtype=int)
    mesh = HydroMesh(vertices=verts, cell_blocks=(CellBlock(CellType.QUADRILATERAL, conn),))
    return solver_mesh_from(
        mesh,
        top=np.array([20.0, 10.0]),
        botm=np.array([[15.0, 5.0], [10.0, 0.0]]),
        inactive_mask=np.zeros((2, 2), dtype=bool),
    )


def test_band_below_the_aquifer_seals_the_nearest_layer_for_continuity() -> None:
    # The wall band [1, 4] m sits below cell 0's aquifer (10-20 m). Without clamping the
    # face emits no row (a leak window in the fence); it is sealed at the nearest (bottom)
    # layer so the cutoff wall stays continuous.
    sm = _stepped_two_cells()
    cut = LineString([(1.0, -0.5), (1.0, 1.5)])
    rows = build_flow_barrier_hfb(
        sm, line=cut, hydchr=1e-9, crest_elevation=4.0, base_elevation=1.0
    )
    assert len(rows) == 1
    assert rows[0][0] == (1, 0) and rows[0][1] == (1, 1)  # bottom layer, face (0, 1)


def test_line_missing_the_mesh_raises() -> None:
    # A declared wall whose trace misses the mesh must fail loudly (the wall is
    # the object of the study), not silently build a model with no barrier.
    sm = _two_layer_grid()
    with pytest.raises(ValueError, match="crosses no interior mesh face"):
        build_flow_barrier_hfb(
            sm, line=LineString([(10.0, 10.0), (11.0, 11.0)]), depths=[5.0], hydchr=1e-9
        )


# HFB rows: layers read on both cells, face weights, open ends and XT3D guard.


def _grid(n: int, botm0: np.ndarray | None = None) -> SolverMesh:
    # n x n unit quads, top = 10, layer 0 bottom = botm0 (default 5), layer 1 bottom = 0.
    verts = np.array([[i, j] for j in range(n + 1) for i in range(n + 1)], dtype=float)

    def v(i: int, j: int) -> int:
        return j * (n + 1) + i

    conn = np.array(
        [[v(i, j), v(i + 1, j), v(i + 1, j + 1), v(i, j + 1)] for j in range(n) for i in range(n)],
        dtype=int,
    )
    mesh = HydroMesh(vertices=verts, cell_blocks=(CellBlock(CellType.QUADRILATERAL, conn),))
    nc = n * n
    b0 = np.full(nc, 5.0) if botm0 is None else botm0
    return solver_mesh_from(
        mesh,
        top=np.full(nc, 10.0),
        botm=np.array([b0, np.zeros(nc)]),
        inactive_mask=np.zeros((2, nc), dtype=bool),
    )


def test_layer_overlap_is_read_on_both_cells() -> None:
    # Cell c1 has a thick top layer (bottom 3 m), c0 a thin one (bottom 5 m).
    # The band [3.5, 4.5] m cuts layer 0 on c1 and layer 1 on c0: both layers are barred.
    sm = _grid(2, botm0=np.array([5.0, 3.0, 5.0, 3.0]))
    line = LineString([(1.01, -0.5), (1.01, 2.5)])
    rows = build_flow_barrier_hfb(sm, line=line, hydchr=1e-9, crest_elevation=4.5, depths=[1.0])
    assert sorted({r[0][0] for r in rows}) == [0, 1]
    assert len(rows) == 4


def test_band_cutting_two_layers_bars_both() -> None:
    sm = _grid(2)
    line = LineString([(1.01, -0.5), (1.01, 2.5)])
    rows = build_flow_barrier_hfb(sm, line=line, hydchr=1e-9, base_elevation=2.0)
    assert sorted({r[0][0] for r in rows}) == [0, 1]


def test_face_hydchr_is_weighted_by_trace_over_chain_length() -> None:
    # A diagonal trace bars a staircase of faces longer than the trace itself.
    sm = _grid(6)
    line = LineString([(0.0, 0.3), (6.0, 5.7)])
    qa: dict = {}
    rows = build_flow_barrier_hfb(sm, line=line, hydchr=1e-6, depths=[2.0], qa=qa)
    edge_len = {}
    geo = sm.cell_mesh.geometry
    for e in np.flatnonzero(geo.edge_cells[:, 1] >= 0):
        a, b = sorted(int(c) for c in geo.edge_cells[e])
        edge_len[(a, b)] = float(geo.edge_length[e])
    total = sum(r[2] * edge_len[tuple(sorted((r[0][1], r[1][1])))] for r in rows)
    trace = line.length
    assert total == pytest.approx(1e-6 * trace, rel=1e-9)
    assert all(r[2] < 1e-6 for r in rows)
    assert qa["chain_over_trace"] > 1.0


def test_open_end_inside_the_mesh_warns_with_the_gap(caplog) -> None:
    sm = _grid(4)
    line = LineString([(2.01, -0.5), (2.01, 2.5)])  # stops 1.5 m short of the top edge
    qa: dict = {}
    with caplog.at_level(logging.WARNING):
        build_flow_barrier_hfb(sm, line=line, hydchr=1e-9, depths=[2.0], qa=qa)
    assert qa["open_length_start"] == pytest.approx(0.0, abs=1e-9)
    assert qa["open_length_end"] == pytest.approx(1.5, abs=1e-9)
    assert any("open" in rec.message for rec in caplog.records if rec.levelno >= logging.WARNING)
    assert qa["faces_per_layer"] == {0: 2}


def _xt3d_model(sinks_sources: dict, xt3d: bool) -> SimpleNamespace:
    return SimpleNamespace(
        flow=SimpleNamespace(sinks_sources=sinks_sources),
        modflow_config=SimpleNamespace(runtime=SimpleNamespace(mf6_enable_xt3d=xt3d)),
    )


def test_zero_hydchr_is_refused_under_xt3d() -> None:
    sm = _grid(2)
    cfg = FlowBarrierConfig(line=[[1.01, -0.5], [1.01, 2.5]], depths=[7.0], hydchr=0.0)
    line = LineString([(1.01, -0.5), (1.01, 2.5)])
    ss: dict = {"flow_barriers": {"w": {"barrier": cfg, "line": line}}}
    with pytest.raises(ValueError, match="XT3D"):
        resolve_flow_barrier_hfb_rows(_xt3d_model(ss, True), sm)
    rows = resolve_flow_barrier_hfb_rows(_xt3d_model(ss, False), sm)
    assert rows and all(r[2] == 0.0 for r in rows)


# resolve_flow_barrier_hfb_rows turns bound barriers into MODFLOW 6 HFB rows.
#
# It reads both the lake ``cutoff_wall`` (trace on ``cutoff_wall_line``) and the
# general ``[flow.sinks_sources.flow_barriers]`` (``{'barrier', 'line'}`` payloads)
# off ``model.flow.sinks_sources`` and builds the HFB rows for every barrier. A
# model without a barrier yields ``[]``; a barrier declared but never bound raises.

# A near-vertical trace across the 2x2 grid bars the connected faces (0, 1) and (2, 3).
_CUT_COORDS = [[1.01, -0.5], [1.01, 2.5]]


_CUT_LINE = LineString([(1.01, -0.5), (1.01, 2.5)])


def _two_layer_grid_2() -> SolverMesh:
    # 2x2 unit quads (c0=(0,0), c1=(1,0), c2=(0,1), c3=(1,1)); top = 10, two 5 m layers.
    verts = np.array([[i, j] for j in range(3) for i in range(3)], dtype=float)

    def v(i: int, j: int) -> int:
        return j * 3 + i

    conn = np.array(
        [[v(i, j), v(i + 1, j), v(i + 1, j + 1), v(i, j + 1)] for j in range(2) for i in range(2)],
        dtype=int,
    )
    mesh = HydroMesh(vertices=verts, cell_blocks=(CellBlock(CellType.QUADRILATERAL, conn),))
    return solver_mesh_from(
        mesh,
        top=np.full(4, 10.0),
        botm=np.array([[5.0] * 4, [0.0] * 4]),
        inactive_mask=np.zeros((2, 4), dtype=bool),
    )


def _model(sinks_sources: dict) -> SimpleNamespace:
    return SimpleNamespace(flow=SimpleNamespace(sinks_sources=sinks_sources))


def test_resolver_builds_rows_for_a_bound_cutoff_wall() -> None:
    wall = FlowBarrierConfig(line=_CUT_COORDS, depths=[7.0], hydchr=1e-9)
    payload = {"cutoff_wall": wall, "cutoff_wall_line": _CUT_LINE}
    rows = resolve_flow_barrier_hfb_rows(
        _model({"lakes": {"reservoir": payload}}), _two_layer_grid_2()
    )
    assert len(rows) == 4  # depth 7 m spans both 5 m layers across the two faces
    assert sorted({r[0][0] for r in rows}) == [0, 1]
    assert all(r[2] == pytest.approx(1e-9) for r in rows)


def test_resolver_builds_rows_for_a_general_flow_barrier() -> None:
    barrier = FlowBarrierConfig(line=_CUT_COORDS, depths=[4.0], hydchr=1e-9)
    payload = {"barrier": barrier, "line": _CUT_LINE}
    rows = resolve_flow_barrier_hfb_rows(
        _model({"flow_barriers": {"wall_a": payload}}), _two_layer_grid_2()
    )
    # depth 4 m stays in the top 5 m layer only => 2 faces, layer 0 only.
    assert sorted({r[0][0] for r in rows}) == [0]
    assert sorted({(r[0][1], r[1][1]) for r in rows}) == [(0, 1), (2, 3)]


def test_resolver_is_empty_without_a_barrier() -> None:
    rows = resolve_flow_barrier_hfb_rows(
        _model({"lakes": {"reservoir": {"bedleak": 1e-6}}}), _two_layer_grid_2()
    )
    assert rows == []


def test_resolver_raises_when_barrier_declared_but_not_bound() -> None:
    barrier = FlowBarrierConfig(line=_CUT_COORDS, depths=[7.0], hydchr=1e-9)
    model = _model({"flow_barriers": {"wall_a": {"barrier": barrier}}})  # no line
    with pytest.raises(ValueError, match="not resolved"):
        resolve_flow_barrier_hfb_rows(model, _two_layer_grid_2())


def test_binder_to_resolver_chain_for_lake_and_general() -> None:
    lake = FlowLakeConfig.model_validate(
        {
            "bedleak": 1e-6,
            "initial_stage": "8 m",
            "cutoff_wall": {"line": _CUT_COORDS, "depths": [4.0], "hydchr": 1e-9},
        }
    )
    barrier = FlowBarrierConfig(line=_CUT_COORDS, depths=[7.0], hydchr=1e-9)
    flow = SimpleNamespace(
        sinks_sources={"lakes": {"reservoir": lake}, "flow_barriers": {"wall_a": barrier}}
    )
    apply_cutoff_wall_to_flow(flow=flow)
    apply_flow_barriers_to_flow(flow=flow)
    rows = resolve_flow_barrier_hfb_rows(SimpleNamespace(flow=flow), _two_layer_grid_2())
    # lake wall (depth 4 -> layer 0, 2 faces) + general barrier (depth 7 -> 2 layers, 4 rows)
    assert len(rows) == 2 + 4
