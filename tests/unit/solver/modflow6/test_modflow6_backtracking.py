"""IMS backtracking control and outer-iteration CSV (finding C-03)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from hydromodpy.solver.modflow6.builders.solver_options import optional_ims_kwargs
from hydromodpy.solver.modflow6.modflow6_config import Modflow6RuntimeConfig


def test_backtracking_number_defaults_to_the_preset() -> None:
    runtime = Modflow6RuntimeConfig()
    assert runtime.mf6_backtracking_number is None
    assert "backtracking_number" not in optional_ims_kwargs(runtime)


def test_backtracking_number_zero_is_written() -> None:
    runtime = Modflow6RuntimeConfig(mf6_backtracking_number=0)
    assert optional_ims_kwargs(runtime)["backtracking_number"] == 0
    with pytest.raises(ValidationError):
        Modflow6RuntimeConfig(mf6_backtracking_number=-1)


def test_backtracking_number_reaches_the_ims_file(tmp_path) -> None:
    import flopy

    runtime = Modflow6RuntimeConfig(mf6_backtracking_number=0)
    sim = flopy.mf6.MFSimulation(sim_ws=str(tmp_path))
    flopy.mf6.ModflowTdis(sim)
    flopy.mf6.ModflowIms(
        sim,
        complexity="COMPLEX",
        filename="t.ims",
        **optional_ims_kwargs(runtime, csv_outer_output="t.outer.csv"),
    )
    sim.write_simulation(silent=True)
    text = " ".join((tmp_path / "t.ims").read_text().upper().split())
    assert "BACKTRACKING_NUMBER 0" in text
    assert "CSV_OUTER_OUTPUT FILEOUT T.OUTER.CSV" in text


def test_csv_outer_output_is_off_by_default() -> None:
    kwargs = optional_ims_kwargs(Modflow6RuntimeConfig())
    assert "csv_outer_output_filerecord" not in kwargs


def _triangle_disv(n: int, size: float):
    """Split an n x n square grid into right triangles; return DISV inputs."""
    import numpy as np

    h = size / n
    vertices = []
    for j in range(n + 1):
        for i in range(n + 1):
            vertices.append([j * (n + 1) + i, i * h, size - j * h])
    cells = []
    k = 0
    for j in range(n):
        for i in range(n):
            a = j * (n + 1) + i
            b, c, d = a + 1, a + n + 2, a + n + 1
            for tri in ((a, b, c), (a, c, d)):
                xs = np.mean([vertices[v][1] for v in tri])
                ys = np.mean([vertices[v][2] for v in tri])
                cells.append([k, xs, ys, 3, *tri])
                k += 1
    return vertices, cells


@pytest.mark.mf6
@pytest.mark.allow_subprocess
def test_triangle_mesh_converges_under_xt3d_newton(tmp_path) -> None:
    """A small unconfined triangle mesh with top drains solves under XT3D."""
    import flopy
    import numpy as np

    from hydromodpy.solver.modflow6.builders.solver_options import newton_options
    from hydromodpy.solver.modflow_common.binaries import ensure_solver_binary

    exe = str(ensure_solver_binary("mf6"))
    runtime = Modflow6RuntimeConfig()  # Newton on, COMPLEX, by default.
    vertices, cells = _triangle_disv(n=12, size=1200.0)
    ncpl = len(cells)
    xc = np.array([c[1] for c in cells])
    top = 50.0 + 0.02 * xc
    sim = flopy.mf6.MFSimulation(sim_name="sim", sim_ws=str(tmp_path), exe_name=exe)
    flopy.mf6.ModflowTdis(sim, nper=1, perioddata=[(86400.0, 1, 1.0)], time_units="seconds")
    flopy.mf6.ModflowIms(
        sim,
        complexity=runtime.mf6_ims_complexity,
        outer_maximum=int(runtime.mf6_outer_maximum),
        **optional_ims_kwargs(runtime),
    )
    gwf = flopy.mf6.ModflowGwf(sim, modelname="tri", newtonoptions=newton_options(runtime))
    flopy.mf6.ModflowGwfdisv(
        gwf,
        nlay=1,
        ncpl=ncpl,
        nvert=len(vertices),
        top=top,
        botm=[0.0],
        vertices=vertices,
        cell2d=cells,
    )
    flopy.mf6.ModflowGwfnpf(gwf, icelltype=1, k=1e-5, xt3doptions=True)
    flopy.mf6.ModflowGwfic(gwf, strt=top)
    flopy.mf6.ModflowGwfsto(gwf, steady_state={0: True}, iconvert=1)
    flopy.mf6.ModflowGwfrcha(gwf, recharge=3e-9)
    drains = [[(0, i), float(top[i]), 1e-5 * 100.0 * 100.0] for i in range(ncpl)]
    flopy.mf6.ModflowGwfdrn(gwf, stress_period_data={0: drains})
    sim.write_simulation(silent=True)
    assert "XT3D" in (tmp_path / "tri.npf").read_text().upper()
    ok, _ = sim.run_simulation(silent=True)
    assert ok


def test_failure_hint_names_xt3d_switch_when_npf_has_xt3d(tmp_path) -> None:
    from hydromodpy.solver.modflow_common.flow_adapter_helpers import xt3d_failure_hint

    (tmp_path / "m.npf").write_text("BEGIN options\n  XT3D\nEND options\n")
    assert "mf6_enable_xt3d = false" in xt3d_failure_hint(tmp_path)
    (tmp_path / "m.npf").write_text("BEGIN options\nEND options\n")
    assert xt3d_failure_hint(tmp_path) == ""
