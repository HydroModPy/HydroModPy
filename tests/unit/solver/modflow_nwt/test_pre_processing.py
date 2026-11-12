"""The flopy packages MODFLOW-NWT is written from, and the vertical conductivity of UPW.

UPW takes ``VKA`` as the vertical conductivity itself when ``LAYVKA`` is 0 in a layer, and as a
ratio of K to Kv otherwise. A model with a ``Kv`` (m/s) gives ``LAYVKA = 0`` and ``VKA = Kv`` in
every layer, converted to the solver time unit. A model without one keeps the
``[solver.modflow_nwt]`` ratio, 1 by default.
"""

from __future__ import annotations

from types import SimpleNamespace

import flopy
import numpy as np
import pytest

from hydromodpy.core.exceptions import ConfigError
from hydromodpy.solver.modflow_nwt.nwt._pre_processing import assemble_flopy_packages
from hydromodpy.solver.modflow_nwt.nwt.nwt_config import (
    ModflowProcessSpecificConfig,
    ModflowSpecifParams,
)

NLAY, NROW, NCOL = 2, 3, 4
SHAPE = (NLAY, NROW, NCOL)
K_M_S = 1e-5
KV_M_S = 2e-6
SECONDS_PER_DAY = 86400.0
FLOAT32_RTOL = 1e-6  # FloPy keeps the package arrays in single precision, 6e-8 relative.
NO_GRID_CHECK = SimpleNamespace(check_grid=False)


def tiny_solver(tmp_path, *, itmuni: int = 1, params: ModflowSpecifParams | None = None):
    mf = flopy.modflow.Modflow("tiny", version="mfnwt", model_ws=str(tmp_path))
    top = np.full((NROW, NCOL), 10.0)
    flopy.modflow.ModflowDis(
        mf,
        nlay=NLAY,
        nrow=NROW,
        ncol=NCOL,
        nper=1,
        top=top,
        botm=[5.0, 0.0],
        perlen=[1.0],
        nstp=[1],
        steady=[True],
        itmuni=itmuni,
    )
    return SimpleNamespace(
        mf=mf,
        dis_itmuni=itmuni,
        nlay=NLAY,
        nper=1,
        nstp=np.array([1]),
        top_elevation=top,
        model_name="tiny",
        _params=params or ModflowSpecifParams(),
    )


def flow_inputs(kv: np.ndarray | None) -> SimpleNamespace:
    ibound = np.ones(SHAPE, dtype=int)
    ibound[:, :, 0] = -1
    strt = np.full(SHAPE, 10.0)
    strt[:, :, 0] = 8.0
    return SimpleNamespace(
        drain_array=np.ones((NROW, NCOL)),
        chd_spd=None,
        ibound=ibound,
        strt=strt,
        hk=np.full(SHAPE, K_M_S),
        hk_value=K_M_S,
        kv=kv,
        sy=np.full(SHAPE, 0.05),
        sy_value=0.05,
        ss=np.full(SHAPE, 1e-5),
        ss_value=1e-5,
        rch_data={0: 1e-8},
        recharge_own_rates={0: 1e-8},
        evt_spd=None,
        drn_spd=None,
        wel_spd=None,
    )


def uniform_kv() -> np.ndarray:
    return np.full(SHAPE, KV_M_S)


def test_upw_reads_kv_as_the_vertical_conductivity(tmp_path):
    solver = tiny_solver(tmp_path)

    assemble_flopy_packages(solver, flow_inputs(uniform_kv()), NO_GRID_CHECK)

    np.testing.assert_array_equal(solver.upw.layvka.array, np.zeros(NLAY, dtype=int))
    np.testing.assert_allclose(solver.upw.vka.array, uniform_kv(), rtol=FLOAT32_RTOL)


def test_kv_follows_the_solver_time_unit_like_k(tmp_path):
    solver = tiny_solver(tmp_path, itmuni=4)  # days

    assemble_flopy_packages(solver, flow_inputs(uniform_kv()), NO_GRID_CHECK)

    np.testing.assert_allclose(solver.upw.vka.array, KV_M_S * SECONDS_PER_DAY, rtol=FLOAT32_RTOL)
    np.testing.assert_allclose(solver.upw.hk.array, K_M_S * SECONDS_PER_DAY, rtol=FLOAT32_RTOL)


def test_kv_per_layer_reaches_each_layer(tmp_path):
    kv = np.stack([np.full((NROW, NCOL), 3e-6), np.full((NROW, NCOL), 4e-7)])
    solver = tiny_solver(tmp_path)

    assemble_flopy_packages(solver, flow_inputs(kv), NO_GRID_CHECK)

    np.testing.assert_allclose(solver.upw.vka.array, kv, rtol=FLOAT32_RTOL)


def test_flow_without_kv_keeps_the_ratio_settings(tmp_path):
    solver = tiny_solver(tmp_path)

    assemble_flopy_packages(solver, flow_inputs(None), NO_GRID_CHECK)

    params = solver._params
    np.testing.assert_array_equal(
        solver.upw.layvka.array, np.full(NLAY, params.runtime.upw.layvka, dtype=int)
    )
    np.testing.assert_array_equal(solver.upw.vka.array, np.full(SHAPE, params.process_specific.vka))


@pytest.mark.nwt
@pytest.mark.binary
@pytest.mark.allow_subprocess
def test_modflow_nwt_reads_vka_as_a_vertical_conductivity(tmp_path):
    from hydromodpy.solver.modflow_common.binaries import ensure_solver_binary

    solver = tiny_solver(tmp_path)
    solver.mf.exe_name = str(ensure_solver_binary("mfnwt"))
    assemble_flopy_packages(solver, flow_inputs(uniform_kv()), NO_GRID_CHECK)
    flopy.modflow.ModflowNwt(solver.mf)
    solver.mf.write_input()

    success, _ = solver.mf.run_model(silent=True)

    assert success
    listing = (tmp_path / "tiny.list").read_text().splitlines()
    rows = [line.split() for line in listing if "NON-WETTABLE" in line]
    assert len(rows) == NLAY
    assert all(" ".join(row[4:6]) == "VERTICAL K" for row in rows), rows


def test_kv_beside_a_vertical_anisotropy_ratio_is_refused(tmp_path):
    params = ModflowSpecifParams(process_specific=ModflowProcessSpecificConfig(vka=10.0))
    solver = tiny_solver(tmp_path, params=params)

    with pytest.raises(ConfigError, match="both set the vertical conductivity"):
        assemble_flopy_packages(solver, flow_inputs(uniform_kv()), NO_GRID_CHECK)
