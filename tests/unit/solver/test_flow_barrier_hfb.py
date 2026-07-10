"""Build MODFLOW 6 HFB rows from a barrier line carved to a depth."""

from __future__ import annotations

import numpy as np
import pytest
from shapely.geometry import LineString

from hydromodpy.solver.modflow6.builders.flow_barrier import build_flow_barrier_hfb
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh
from hydromodpy.spatial.mesh.cell_types import CellType
from hydromodpy.spatial.mesh.hydro_mesh import CellBlock, HydroMesh

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
    return SolverMesh(
        planar_mesh=mesh,
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


def test_line_missing_the_mesh_raises() -> None:
    # A declared wall whose trace misses the mesh must fail loudly (the wall is
    # the object of the study), not silently build a model with no barrier.
    sm = _two_layer_grid()
    with pytest.raises(ValueError, match="crosses no interior mesh face"):
        build_flow_barrier_hfb(
            sm, line=LineString([(10.0, 10.0), (11.0, 11.0)]), depths=[5.0], hydchr=1e-9
        )
