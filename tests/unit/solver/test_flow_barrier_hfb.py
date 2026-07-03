"""Build MODFLOW 6 HFB rows from a barrier line carved to a depth."""

from __future__ import annotations

import numpy as np
import pytest
from shapely.geometry import LineString

from hydromodpy.solver.modflow6.builders.flow_barrier import build_flow_barrier_hfb
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh
from hydromodpy.spatial.mesh.cell_types import CellType
from hydromodpy.spatial.mesh.hydro_mesh import CellBlock, HydroMesh


def _two_layer_row() -> SolverMesh:
    vertices = np.array(
        [[0, 0], [1, 0], [2, 0], [3, 0], [0, 1], [1, 1], [2, 1], [3, 1]], dtype=float
    )
    conn = np.array([[0, 1, 5, 4], [1, 2, 6, 5], [2, 3, 7, 6]], dtype=int)
    mesh = HydroMesh(vertices=vertices, cell_blocks=(CellBlock(CellType.QUADRILATERAL, conn),))
    # top = 10, two 5 m layers.
    return SolverMesh(
        planar_mesh=mesh,
        top=np.full(3, 10.0),
        botm=np.array([[5.0, 5.0, 5.0], [0.0, 0.0, 0.0]]),
        inactive_mask=np.zeros((2, 3), dtype=bool),
    )


def test_shallow_depth_spans_top_layer_only() -> None:
    sm = _two_layer_row()
    rows = build_flow_barrier_hfb(
        sm, line=LineString([(0.5, 0.5), (2.5, 0.5)]), depths=[4.0], hydchr=1e-9
    )
    assert sorted({r[0][0] for r in rows}) == [0]
    assert sorted({(r[0][1], r[1][1]) for r in rows}) == [(0, 1), (1, 2)]


def test_deep_depth_spans_both_layers() -> None:
    sm = _two_layer_row()
    rows = build_flow_barrier_hfb(
        sm, line=LineString([(0.5, 0.5), (2.5, 0.5)]), depths=[7.0], hydchr=1e-9
    )
    assert sorted({r[0][0] for r in rows}) == [0, 1]
    assert len(rows) == 4
    assert all(r[2] == 1e-9 for r in rows)


def test_per_segment_depth_is_interpolated_along_the_line() -> None:
    sm = _two_layer_row()
    # shallow (4 m) at the start, deep (7 m) at the end of the line.
    rows = build_flow_barrier_hfb(
        sm, line=LineString([(0.5, 0.5), (2.5, 0.5)]), depths=[4.0, 7.0], hydchr=1e-9
    )
    by_face: dict[tuple[int, int], list[int]] = {}
    for r in rows:
        by_face.setdefault((r[0][1], r[1][1]), []).append(r[0][0])
    # first face stays shallow (layer 0), the deeper end reaches layer 1
    assert by_face[(0, 1)] == [0]
    assert sorted(by_face[(1, 2)]) == [0, 1]


def test_line_missing_the_mesh_raises() -> None:
    # A declared wall whose trace misses the mesh must fail loudly (the wall is
    # the object of the study), not silently build a model with no barrier.
    sm = _two_layer_row()
    with pytest.raises(ValueError, match="crosses no interior mesh face"):
        build_flow_barrier_hfb(
            sm, line=LineString([(10.0, 10.0), (11.0, 11.0)]), depths=[5.0], hydchr=1e-9
        )
