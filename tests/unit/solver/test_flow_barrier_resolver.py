"""resolve_flow_barrier_hfb_rows turns bound barriers into MODFLOW 6 HFB rows.

It reads both the lake ``cutoff_wall`` (trace on ``cutoff_wall_line``) and the
general ``[flow.sinks_sources.flow_barriers]`` (``{'barrier', 'line'}`` payloads)
off ``model.flow.sinks_sources`` and builds the HFB rows for every barrier. A
model without a barrier yields ``[]``; a barrier declared but never bound raises.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest
from shapely.geometry import LineString

from hydromodpy.physics.flow.sinks_sources import FlowBarrierConfig, FlowLakeConfig
from hydromodpy.physics.flow.structure_binders import (
    apply_cutoff_wall_to_flow,
    apply_flow_barriers_to_flow,
)
from hydromodpy.solver.modflow6.builders.flow_barrier import resolve_flow_barrier_hfb_rows
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh
from hydromodpy.spatial.mesh.cell_types import CellType
from hydromodpy.spatial.mesh.hydro_mesh import CellBlock, HydroMesh

# A near-vertical trace across the 2x2 grid bars the connected faces (0, 1) and (2, 3).
_CUT_COORDS = [[1.01, -0.5], [1.01, 2.5]]
_CUT_LINE = LineString([(1.01, -0.5), (1.01, 2.5)])


def _two_layer_grid() -> SolverMesh:
    # 2x2 unit quads (c0=(0,0), c1=(1,0), c2=(0,1), c3=(1,1)); top = 10, two 5 m layers.
    verts = np.array([[i, j] for j in range(3) for i in range(3)], dtype=float)

    def v(i: int, j: int) -> int:
        return j * 3 + i

    conn = np.array(
        [[v(i, j), v(i + 1, j), v(i + 1, j + 1), v(i, j + 1)] for j in range(2) for i in range(2)],
        dtype=int,
    )
    mesh = HydroMesh(vertices=verts, cell_blocks=(CellBlock(CellType.QUADRILATERAL, conn),))
    return SolverMesh(
        planar_mesh=mesh,
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
        _model({"lakes": {"reservoir": payload}}), _two_layer_grid()
    )
    assert len(rows) == 4  # depth 7 m spans both 5 m layers across the two faces
    assert sorted({r[0][0] for r in rows}) == [0, 1]
    assert all(r[2] == pytest.approx(1e-9) for r in rows)


def test_resolver_builds_rows_for_a_general_flow_barrier() -> None:
    barrier = FlowBarrierConfig(line=_CUT_COORDS, depths=[4.0], hydchr=1e-9)
    payload = {"barrier": barrier, "line": _CUT_LINE}
    rows = resolve_flow_barrier_hfb_rows(
        _model({"flow_barriers": {"wall_a": payload}}), _two_layer_grid()
    )
    # depth 4 m stays in the top 5 m layer only => 2 faces, layer 0 only.
    assert sorted({r[0][0] for r in rows}) == [0]
    assert sorted({(r[0][1], r[1][1]) for r in rows}) == [(0, 1), (2, 3)]


def test_resolver_is_empty_without_a_barrier() -> None:
    rows = resolve_flow_barrier_hfb_rows(
        _model({"lakes": {"reservoir": {"bedleak": 1e-6}}}), _two_layer_grid()
    )
    assert rows == []


def test_resolver_raises_when_barrier_declared_but_not_bound() -> None:
    barrier = FlowBarrierConfig(line=_CUT_COORDS, depths=[7.0], hydchr=1e-9)
    model = _model({"flow_barriers": {"wall_a": {"barrier": barrier}}})  # no line
    with pytest.raises(ValueError, match="not resolved"):
        resolve_flow_barrier_hfb_rows(model, _two_layer_grid())


def test_binder_to_resolver_chain_for_lake_and_general() -> None:
    lake = FlowLakeConfig.model_validate(
        {
            "bedleak": 1e-6,
            "stageinit": "8 m",
            "cutoff_wall": {"line": _CUT_COORDS, "depths": [4.0], "hydchr": 1e-9},
        }
    )
    barrier = FlowBarrierConfig(line=_CUT_COORDS, depths=[7.0], hydchr=1e-9)
    flow = SimpleNamespace(
        sinks_sources={"lakes": {"reservoir": lake}, "flow_barriers": {"wall_a": barrier}}
    )
    apply_cutoff_wall_to_flow(flow=flow)
    apply_flow_barriers_to_flow(flow=flow)
    rows = resolve_flow_barrier_hfb_rows(SimpleNamespace(flow=flow), _two_layer_grid())
    # lake wall (depth 4 -> layer 0, 2 faces) + general barrier (depth 7 -> 2 layers, 4 rows)
    assert len(rows) == 2 + 4
