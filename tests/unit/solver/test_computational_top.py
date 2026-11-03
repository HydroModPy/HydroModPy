"""DISV vertices are written with enough digits for a sub-millimeter face (DISV-PREC)."""

from __future__ import annotations

import flopy
import numpy as np

from hydromodpy.solver.modflow6.support.computational_top import (
    set_simulation_float_precision,
)


def test_disv_vertices_round_trip_below_a_micrometre(tmp_path):
    """Lambert-93 vertices keep 1e-6 m once written and read back by flopy."""
    x0, y0 = 351234.56789012, 6789012.34567891
    verts = [
        (0, x0, y0),
        (1, x0 + 100.0, y0),
        (2, x0 + 100.0, y0 + 100.0),
        (3, x0 + 0.0123456, y0 + 100.0),
    ]
    sim = flopy.mf6.MFSimulation(sim_name="p", sim_ws=str(tmp_path))
    set_simulation_float_precision(sim)
    flopy.mf6.ModflowTdis(sim)
    gwf = flopy.mf6.ModflowGwf(sim, modelname="p")
    flopy.mf6.ModflowGwfdisv(
        gwf,
        nlay=1,
        ncpl=1,
        nvert=4,
        top=10.0,
        botm=[0.0],
        vertices=verts,
        cell2d=[(0, x0 + 50.0, y0 + 50.0, 4, 0, 1, 2, 3)],
    )
    sim.write_simulation()
    text = (tmp_path / "p.disv").read_text()
    rows = [
        ln.split() for ln in text.splitlines() if ln.strip().startswith(("1 ", "2 ", "3 ", "4 "))
    ]
    rows = [r for r in rows if len(r) == 3]
    read = np.array([[float(r[1]), float(r[2])] for r in rows])
    expected = np.array([[v[1], v[2]] for v in verts])
    assert np.abs(read - expected).max() < 1e-6
