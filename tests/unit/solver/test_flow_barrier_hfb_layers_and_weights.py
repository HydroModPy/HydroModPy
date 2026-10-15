"""HFB rows: layers read on both cells, face weights, open ends and XT3D guard."""

from __future__ import annotations

import logging
from types import SimpleNamespace

import numpy as np
import pytest
from shapely.geometry import LineString

from hydromodpy.physics.flow.sinks_sources import FlowBarrierConfig
from hydromodpy.solver.modflow6.builders.flow_barrier import (
    build_flow_barrier_hfb,
    resolve_flow_barrier_hfb_rows,
)
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh
from hydromodpy.spatial.mesh.model.cell_types import CellType
from hydromodpy.spatial.mesh.model.hydro_mesh import CellBlock, HydroMesh
from tests._helpers.solver_meshes import solver_mesh_from


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
