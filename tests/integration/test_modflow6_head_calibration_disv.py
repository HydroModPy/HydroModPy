"""Head calibration reads a DISV head array correctly off the first grid row.

MF6 always writes DISV, whose head array is ``(nlay, 1, ncpl)``. The station-cell
resolver returns structured ``(layer, row, col)`` tuples, so the MF6 adapter must
collapse them to the flat ``(layer, 0, cell2d)`` id before reading the head;
otherwise ``head[layer, row, col]`` indexes the size-1 middle axis and raises for
any station off row 0. This guards that bug end to end on a real MF6 run.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.solver.modflow6.adapters.flow import _collapse_to_disv_cells
from hydromodpy.solver.modflow_common.binaries import ensure_solver_binary
from hydromodpy.solver.modflow_common.calibration_extractors import extract_head_from_hds
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh


def test_collapse_to_disv_cells_flattens_row_col() -> None:
    # A structured (layer, row, col) collapses to the row-major flat cell2d id with
    # the middle axis pinned to 0 (the DISV degenerate row).
    model = SimpleNamespace(solver_mesh=SimpleNamespace(is_structured=True, ncol=3))
    out = _collapse_to_disv_cells({"a": (0, 0, 0), "b": (0, 1, 2)}, model)
    assert out == {"a": (0, 0, 0), "b": (0, 0, 5)}


def test_collapse_passes_unstructured_cells_through() -> None:
    model = SimpleNamespace(solver_mesh=SimpleNamespace(is_structured=False))
    cells = {"a": (0, 0, 7)}
    assert _collapse_to_disv_cells(cells, model) == cells


@pytest.mark.mf6
@pytest.mark.binary
@pytest.mark.allow_subprocess
@pytest.mark.fast
def test_extract_head_from_hds_reads_disv_off_row_zero(tmp_path: Path) -> None:
    import flopy
    import flopy.utils.binaryfile as bf

    exe = str(ensure_solver_binary("mf6"))
    nrow = ncol = 3
    name = "mhd"
    top = np.full((nrow, ncol), 10.0)
    botm = np.zeros((1, nrow, ncol))
    # Build the DISV grid through the production abstraction (fake-structured DISV).
    mesh = SolverMesh.from_structured_arrays(nrow=nrow, ncol=ncol, top=top, botm=botm, dx=1.0, dy=1.0)

    sim = flopy.mf6.MFSimulation(sim_name=name, sim_ws=str(tmp_path), exe_name=exe)
    flopy.mf6.ModflowTdis(sim, nper=1, perioddata=[(1.0, 1, 1.0)])
    flopy.mf6.ModflowIms(sim, complexity="SIMPLE")
    gwf = flopy.mf6.ModflowGwf(sim, modelname=name)
    flopy.mf6.ModflowGwfdisv(gwf, nlay=1, **mesh.to_disv_kwargs(), idomain=mesh.idomain())
    flopy.mf6.ModflowGwfnpf(gwf, k=1.0)
    flopy.mf6.ModflowGwfic(gwf, strt=5.0)
    # West column high, east column low: every column gets a distinct head, so a
    # wrong (row, col) index would read the wrong value, not just raise.
    chd = []
    for r in range(nrow):
        chd.append([(0, r * ncol + 0), 8.0])
        chd.append([(0, r * ncol + (ncol - 1)), 2.0])
    flopy.mf6.ModflowGwfchd(gwf, stress_period_data={0: chd})
    flopy.mf6.ModflowGwfoc(gwf, head_filerecord=f"{name}.hds", saverecord=[("HEAD", "ALL")])
    sim.write_simulation(silent=True)
    ok, _ = sim.run_simulation(silent=True)
    assert ok, "the DISV head model did not converge"

    raw = bf.HeadFile(str(tmp_path / f"{name}.hds")).get_data()
    assert raw.shape == (1, 1, nrow * ncol)

    # Station at row 1, col 1 (off the first row). The MF6 adapter collapses
    # (0, 1, 1) -> (0, 0, 4); the reader must return that cell's head.
    flat = 1 * ncol + 1
    series = extract_head_from_hds(tmp_path, name, station_cells={"s": (0, 0, flat)})
    assert series["s"].iloc[-1] == pytest.approx(float(raw[0, 0, flat]))

    # The old structured tuple (0, row>0, col) indexes the size-1 middle axis and
    # raises: this is exactly the bug the adapter collapse prevents.
    with pytest.raises(IndexError):
        extract_head_from_hds(tmp_path, name, station_cells={"s": (0, 1, 1)})
