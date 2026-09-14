"""A configured HFB wall really blocks cross-wall flow in a MODFLOW 6 solve.

Mirrors the lake-marnage integration test: build the HFB rows through the real
``build_flow_barrier_hfb`` path, attach ``ModflowGwfhfb``, run mf6, and assert a
head discontinuity across the wall and a collapsed cross-wall flux versus a
no-HFB control. Structural unit tests never exercise a real solve.
"""

from __future__ import annotations

import numpy as np
import pytest
from shapely.geometry import LineString

from hydromodpy.solver.modflow6.builders.flow_barrier import build_flow_barrier_hfb
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh
from hydromodpy.spatial.mesh.adapters.flopy_adapter import to_flopy_disv_args
from hydromodpy.spatial.mesh.model.cell_types import CellType
from hydromodpy.spatial.mesh.model.hydro_mesh import CellBlock, HydroMesh

_N = 11  # cells in a single row; the interior face at x = 5 carries the wall.
_TOP = 10.0
_WALL_FACE_X = 5.0  # face between cell 4 and cell 5


def _row_solver_mesh() -> SolverMesh:
    bottom = np.array([[i, 0.0] for i in range(_N + 1)], dtype=float)
    top = np.array([[i, 1.0] for i in range(_N + 1)], dtype=float)
    vertices = np.vstack([bottom, top])
    conn = np.array([[i, i + 1, (_N + 1) + i + 1, (_N + 1) + i] for i in range(_N)], dtype=int)
    mesh = HydroMesh(vertices=vertices, cell_blocks=(CellBlock(CellType.QUADRILATERAL, conn),))
    return SolverMesh(
        planar_mesh=mesh,
        top=np.full(_N, _TOP),
        botm=np.zeros((1, _N)),
        inactive_mask=np.zeros((1, _N), dtype=bool),
    )


def _build_and_run(tmp_path, *, hfb_rows) -> tuple[np.ndarray, float]:
    import flopy

    from hydromodpy.solver.modflow_common.binaries import ensure_solver_binary

    sm = _row_solver_mesh()
    kw = to_flopy_disv_args(sm.planar_mesh, top=_TOP, botm=sm.botm)
    exe = str(ensure_solver_binary("mf6"))
    sim = flopy.mf6.MFSimulation(sim_name="hfb", sim_ws=str(tmp_path), exe_name=exe)
    flopy.mf6.ModflowTdis(sim, nper=1, perioddata=[(1.0, 1, 1.0)])
    flopy.mf6.ModflowIms(sim, complexity="SIMPLE", outer_dvclose=1e-9, inner_dvclose=1e-10)
    gwf = flopy.mf6.ModflowGwf(sim, modelname="hfb", save_flows=True)
    flopy.mf6.ModflowGwfdisv(
        gwf,
        nlay=1,
        ncpl=kw["ncpl"],
        nvert=kw["nvert"],
        top=_TOP,
        botm=0.0,
        vertices=kw["vertices"],
        cell2d=kw["cell2d"],
    )
    flopy.mf6.ModflowGwfic(gwf, strt=5.0)
    flopy.mf6.ModflowGwfnpf(gwf, icelltype=0, k=1.0)  # confined, TPFA, XT3D off
    flopy.mf6.ModflowGwfchd(gwf, stress_period_data=[[(0, 0), 10.0], [(0, _N - 1), 1.0]])
    if hfb_rows:
        flopy.mf6.ModflowGwfhfb(gwf, stress_period_data=hfb_rows)
    flopy.mf6.ModflowGwfoc(
        gwf,
        head_filerecord="hfb.hds",
        budget_filerecord="hfb.cbc",
        saverecord=[("HEAD", "ALL"), ("BUDGET", "ALL")],
    )
    sim.write_simulation(silent=True)
    ok, _ = sim.run_simulation(silent=True)
    assert ok, "HFB test model did not converge"
    heads = flopy.utils.HeadFile(str(tmp_path / "hfb.hds")).get_data().ravel()
    cbc = flopy.utils.CellBudgetFile(str(tmp_path / "hfb.cbc"))
    chd = cbc.get_data(text="CHD")[0]
    inflow = float(sum(rec["q"] for rec in chd if rec["q"] > 0.0))
    return heads, inflow


@pytest.mark.mf6
@pytest.mark.binary
@pytest.mark.allow_subprocess
@pytest.mark.integration
def test_hfb_wall_blocks_cross_wall_flow(tmp_path) -> None:
    sm = _row_solver_mesh()
    # The trace runs ACROSS the row: the builder bars a face when the line
    # crosses the segment joining the two cell centroids, so a wall drawn along
    # that segment (both centroids sit at y = 0.5) would bar nothing.
    rows = build_flow_barrier_hfb(
        sm,
        line=LineString([(_WALL_FACE_X, -0.5), (_WALL_FACE_X, 1.5)]),
        depths=[_TOP],
        hydchr=1e-9,
    )
    assert [(r[0][1], r[1][1]) for r in rows] == [(4, 5)]

    base_heads, base_inflow = _build_and_run(tmp_path / "base", hfb_rows=None)
    wall_heads, wall_inflow = _build_and_run(tmp_path / "wall", hfb_rows=rows)

    # Control: smooth gradient, small head jump across the middle face.
    assert abs(base_heads[4] - base_heads[5]) < 2.0
    # With the wall: upstream pinned near 10, downstream near 1, a large jump.
    assert wall_heads[4] - wall_heads[5] > 5.0
    assert wall_heads[:5].min() > 8.0
    assert wall_heads[5:].max() < 3.0
    # Cross-wall through-flow collapses.
    assert wall_inflow < 0.01 * base_inflow
