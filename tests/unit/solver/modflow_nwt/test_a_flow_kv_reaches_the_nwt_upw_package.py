"""A ``Kv`` of the model is the vertical conductivity MODFLOW-NWT reads.

The UPW package takes ``VKA`` as the vertical conductivity itself when ``LAYVKA`` is
0 in a layer, and as a ratio of K to Kv otherwise. A model with a ``Kv`` gives UPW
``LAYVKA = 0`` and ``VKA = Kv`` in every layer, converted to the solver time unit. A
model without one keeps the ``[solver.modflow_nwt]`` settings, a ratio of 1 by default.
"""

from __future__ import annotations

from types import SimpleNamespace

import flopy
import numpy as np
import pytest

from hydromodpy.core.exceptions import ConfigError, DataContractViolation
from hydromodpy.model.model import ModelTime, Properties
from hydromodpy.solver.modflow_nwt.nwt._pre_processing import assemble_flopy_packages
from hydromodpy.solver.modflow_nwt.nwt.flow_to_modflow_adapter import FlowToModflowAdapter
from hydromodpy.solver.modflow_nwt.nwt.nwt_config import (
    ModflowProcessSpecificConfig,
    ModflowSpecifParams,
)
from tests._helpers.model_factory import make_model
from tests._helpers.solver_meshes import solver_mesh_from_structured_arrays

NLAY, NROW, NCOL = 2, 3, 4
SHAPE = (NLAY, NROW, NCOL)
K_M_S = 1e-5
KV_M_S = 2e-6
SECONDS_PER_DAY = 86400.0
FLOAT32_RTOL = 1e-6
"""FloPy keeps the package arrays in single precision, 6e-8 relative."""


class _Homogeneous:
    """A flow parameter with one value everywhere."""

    is_heterogeneous = False

    def __init__(self, value: float) -> None:
        self.value = value

    def to_mesh_field(self, mesh, label, depth):
        return SimpleNamespace(cell_values=np.full(mesh.n_cells, self.value))


def _adapter(
    parameters: dict[str, object], steady: tuple[bool, ...] = (True,), **overrides: float
) -> FlowToModflowAdapter:
    dem = np.full((NROW, NCOL), 20.0)
    model = make_model(
        properties=Properties(profiles=parameters),
        time=ModelTime(
            grid=None, regime="steady" if all(steady) else "transient", first_period_steady=True
        ),
    ).with_properties(**overrides)
    mesh = solver_mesh_from_structured_arrays(
        nrow=NROW, ncol=NCOL, top=dem, botm=np.stack([dem - 10.0, dem - 20.0]), dx=5.0, dy=5.0
    )
    return FlowToModflowAdapter(
        model=model,
        solver_mesh=mesh,
        nper=len(steady),
        sink_fill=False,
        steady=np.array(steady),
    )


def _solver(tmp_path, *, itmuni: int = 1, params: ModflowSpecifParams | None = None):
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


def _flow_inputs(kv: np.ndarray | None) -> SimpleNamespace:
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


def test_the_adapter_hands_the_flow_kv_to_the_solver() -> None:
    inputs = _adapter({"K": _Homogeneous(K_M_S), "Kv": _Homogeneous(KV_M_S)}).build()
    assert inputs.kv.shape == SHAPE
    np.testing.assert_array_equal(inputs.kv, KV_M_S)


def test_a_flow_without_kv_hands_none() -> None:
    assert _adapter({"K": _Homogeneous(K_M_S)}).build().kv is None


@pytest.mark.parametrize("name", ["K", "Kv"])
def test_a_per_cell_override_of_the_model_wins_over_its_profile(name) -> None:
    profiles = {"K": _Homogeneous(K_M_S), "Kv": _Homogeneous(KV_M_S)}

    inputs = _adapter(profiles, **{name: 3e-5}).build()

    np.testing.assert_array_equal(getattr(inputs, "hk" if name == "K" else "kv"), 3e-5)
    other = inputs.kv if name == "K" else inputs.hk
    np.testing.assert_array_equal(other, KV_M_S if name == "K" else K_M_S)


def test_an_override_without_a_profile_gives_kv_to_a_model_that_had_none() -> None:
    inputs = _adapter({"K": _Homogeneous(K_M_S)}, Kv=KV_M_S).build()

    np.testing.assert_array_equal(inputs.kv, KV_M_S)


@pytest.mark.parametrize(
    ("values", "steady", "match"),
    [({"Kv": 0.0}, (True,), "Kv"),
     ({"Sy": 0.0, "Ss": 1e-5}, (True, False), r"Sy .* 24 of 24 active convertible .*layer 1: 12, layer 2: 12"),
     ({"Sy": 0.0, "Ss": 1e-5}, (True,), None),
     ({"Sy": 0.1, "Ss": 0.0}, (True, False), None)],
    ids=["kv-zero", "sy-zero-transient", "sy-zero-steady", "ss-zero-convertible"],
)  # fmt: skip
def test_a_value_the_solver_reads_as_zero_is_refused_before_it_runs(values, steady, match) -> None:
    parameters = {"K": _Homogeneous(K_M_S)} | {k: _Homogeneous(v) for k, v in values.items()}
    adapter = _adapter(parameters, steady)
    if match is None:
        adapter.build()
        return
    with pytest.raises(DataContractViolation, match=match):
        adapter.build()


def test_upw_reads_kv_as_the_vertical_conductivity(tmp_path) -> None:
    solver = _solver(tmp_path)
    assemble_flopy_packages(
        solver, _flow_inputs(np.full(SHAPE, KV_M_S)), SimpleNamespace(check_grid=False)
    )
    np.testing.assert_array_equal(solver.upw.layvka.array, np.zeros(NLAY, dtype=int))
    np.testing.assert_allclose(solver.upw.vka.array, np.full(SHAPE, KV_M_S), rtol=FLOAT32_RTOL)


def test_kv_follows_the_solver_time_unit_like_k(tmp_path) -> None:
    solver = _solver(tmp_path, itmuni=4)
    assemble_flopy_packages(
        solver, _flow_inputs(np.full(SHAPE, KV_M_S)), SimpleNamespace(check_grid=False)
    )
    np.testing.assert_allclose(solver.upw.vka.array, KV_M_S * SECONDS_PER_DAY, rtol=FLOAT32_RTOL)
    np.testing.assert_allclose(solver.upw.hk.array, K_M_S * SECONDS_PER_DAY, rtol=FLOAT32_RTOL)


def test_a_kv_per_layer_reaches_each_layer(tmp_path) -> None:
    kv = np.stack([np.full((NROW, NCOL), 3e-6), np.full((NROW, NCOL), 4e-7)])
    solver = _solver(tmp_path)
    assemble_flopy_packages(solver, _flow_inputs(kv), SimpleNamespace(check_grid=False))
    np.testing.assert_allclose(solver.upw.vka.array, kv, rtol=FLOAT32_RTOL)


def test_a_flow_without_kv_keeps_the_ratio_settings(tmp_path) -> None:
    solver = _solver(tmp_path)
    assemble_flopy_packages(solver, _flow_inputs(None), SimpleNamespace(check_grid=False))
    params = solver._params
    np.testing.assert_array_equal(
        solver.upw.layvka.array, np.full(NLAY, params.runtime.upw.layvka, dtype=int)
    )
    np.testing.assert_array_equal(solver.upw.vka.array, np.full(SHAPE, params.process_specific.vka))


def test_a_kv_beside_a_vertical_anisotropy_ratio_is_refused(tmp_path) -> None:
    params = ModflowSpecifParams(process_specific=ModflowProcessSpecificConfig(vka=10.0))
    solver = _solver(tmp_path, params=params)
    with pytest.raises(ConfigError, match="both set the vertical conductivity"):
        assemble_flopy_packages(
            solver, _flow_inputs(np.full(SHAPE, KV_M_S)), SimpleNamespace(check_grid=False)
        )


@pytest.mark.nwt
@pytest.mark.binary
@pytest.mark.allow_subprocess
def test_modflow_nwt_reads_the_vka_it_is_given_as_a_vertical_conductivity(tmp_path) -> None:
    from hydromodpy.solver.modflow_common.binaries import ensure_solver_binary

    solver = _solver(tmp_path)
    solver.mf.exe_name = str(ensure_solver_binary("mfnwt"))
    assemble_flopy_packages(
        solver, _flow_inputs(np.full(SHAPE, KV_M_S)), SimpleNamespace(check_grid=False)
    )
    flopy.modflow.ModflowNwt(solver.mf)
    solver.mf.write_input()
    success, _ = solver.mf.run_model(silent=True)
    assert success
    listing = (tmp_path / "tiny.list").read_text().splitlines()
    rows = [line.split() for line in listing if "NON-WETTABLE" in line]
    assert len(rows) == NLAY
    assert all(" ".join(row[4:6]) == "VERTICAL K" for row in rows), rows
