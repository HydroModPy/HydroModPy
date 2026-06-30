"""resolve_cutoff_wall_hfb_rows turns bound lake walls into MODFLOW 6 HFB rows.

The structure binder attaches a shapely ``cutoff_wall_line`` and the typed
``cutoff_wall`` config onto each lake payload. The resolver reads them off
``model.flow.sinks_sources['lakes']`` and builds the HFB rows for every wall.
A model without a wall yields ``[]``; a wall declared but never bound raises.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest
from shapely.geometry import LineString

from hydromodpy.physics.flow.sinks_sources import CutoffWallConfig, FlowLakeConfig
from hydromodpy.physics.flow.structure_binders import apply_cutoff_wall_to_flow
from hydromodpy.solver.modflow6.builders.flow_barrier import resolve_cutoff_wall_hfb_rows
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh
from hydromodpy.spatial.mesh.cell_types import CellType
from hydromodpy.spatial.mesh.hydro_mesh import CellBlock, HydroMesh


def _two_layer_row() -> SolverMesh:
    vertices = np.array(
        [[0, 0], [1, 0], [2, 0], [3, 0], [0, 1], [1, 1], [2, 1], [3, 1]], dtype=float
    )
    conn = np.array([[0, 1, 5, 4], [1, 2, 6, 5], [2, 3, 7, 6]], dtype=int)
    mesh = HydroMesh(vertices=vertices, cell_blocks=(CellBlock(CellType.QUADRILATERAL, conn),))
    return SolverMesh(
        planar_mesh=mesh,
        top=np.full(3, 10.0),
        botm=np.array([[5.0, 5.0, 5.0], [0.0, 0.0, 0.0]]),
        inactive_mask=np.zeros((2, 3), dtype=bool),
    )


def _model_with_lakes(lakes: dict) -> SimpleNamespace:
    return SimpleNamespace(flow=SimpleNamespace(sinks_sources={"lakes": lakes}))


def test_resolver_builds_rows_for_a_bound_wall() -> None:
    wall = CutoffWallConfig(line=[[0.5, 0.5], [2.5, 0.5]], depths=[7.0], hydchr=1e-9)
    payload = {"cutoff_wall": wall, "cutoff_wall_line": LineString([(0.5, 0.5), (2.5, 0.5)])}
    rows = resolve_cutoff_wall_hfb_rows(_model_with_lakes({"reservoir": payload}), _two_layer_row())
    # depth 7 m spans both 5 m layers across the two interior faces => 4 rows.
    assert len(rows) == 4
    assert sorted({r[0][0] for r in rows}) == [0, 1]
    assert all(r[2] == pytest.approx(1e-9) for r in rows)


def test_resolver_is_empty_without_a_wall() -> None:
    payload = {"bedleak": 1e-6}
    rows = resolve_cutoff_wall_hfb_rows(_model_with_lakes({"reservoir": payload}), _two_layer_row())
    assert rows == []


def test_resolver_raises_when_wall_declared_but_not_bound() -> None:
    wall = CutoffWallConfig(line=[[0.5, 0.5], [2.5, 0.5]], depths=[7.0], hydchr=1e-9)
    payload = {"cutoff_wall": wall}  # no cutoff_wall_line attached
    with pytest.raises(ValueError, match="not resolved"):
        resolve_cutoff_wall_hfb_rows(_model_with_lakes({"reservoir": payload}), _two_layer_row())


def test_binder_to_resolver_chain() -> None:
    lake = FlowLakeConfig.model_validate(
        {
            "bedleak": 1e-6,
            "stageinit": "8 m",
            "cutoff_wall": {"line": [[0.5, 0.5], [2.5, 0.5]], "depths": [4.0], "hydchr": 1e-9},
        }
    )
    flow = SimpleNamespace(sinks_sources={"lakes": {"reservoir": lake}})
    apply_cutoff_wall_to_flow(flow=flow)
    rows = resolve_cutoff_wall_hfb_rows(SimpleNamespace(flow=flow), _two_layer_row())
    # depth 4 m stays in the top 5 m layer only => 2 faces, layer 0 only.
    assert sorted({r[0][0] for r in rows}) == [0]
    assert sorted({(r[0][1], r[1][1]) for r in rows}) == [(0, 1), (1, 2)]
