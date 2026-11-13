"""The MF6 GWT transport model decays a solute, follows the flow solver complexity and starts steady.

Rates are in 1/s for first order decay and in concentration per s for zero order decay.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import flopy
import numpy as np
import pytest

from hydromodpy.mesh.planar.cell_types import CellType
from hydromodpy.mesh.planar.hydro_mesh import CellBlock, HydroMesh
from hydromodpy.model.transport.transport_config import (
    ConcentrationTransportParametersConfig,
)
from hydromodpy.solver.modflow6.modflow6_config import _coerce_modflow6_config
from hydromodpy.solver.modflow6.transport import _MT_S1, Modflow6Transport
from hydromodpy.solver.modflow_common.runtime_arrays import _normalize_sconc_input
from tests._helpers.model_factory import make_model
from tests._helpers.solver_meshes import solver_mesh_from


def build_gwt(tmp_path: Path, params: dict, *, complexity: str = "COMPLEX") -> Modflow6Transport:
    ncpl = 3
    sim = flopy.mf6.MFSimulation(sim_name="sim", sim_ws=str(tmp_path), exe_name="mf6")
    flopy.mf6.ModflowTdis(sim, nper=1, perioddata=[(1.0, 1, 1.0)], time_units="seconds")
    gwf = flopy.mf6.ModflowGwf(sim, modelname="flow", save_flows=True)
    ims = flopy.mf6.ModflowIms(sim, filename="flow.ims")
    sim.register_ims_package(ims, [gwf.name])
    vertices = np.array(
        [[0, 0], [1, 0], [2, 0], [3, 0], [0, 1], [1, 1], [2, 1], [3, 1]], dtype=float
    )
    conn = np.array([[0, 1, 5, 4], [1, 2, 6, 5], [2, 3, 7, 6]], dtype=int)
    mesh = solver_mesh_from(
        HydroMesh(vertices=vertices, cell_blocks=(CellBlock(CellType.QUADRILATERAL, conn),)),
        top=np.full(ncpl, 10.0),
        botm=np.zeros((1, ncpl)),
        inactive_mask=np.zeros((1, ncpl), dtype=bool),
    )
    flopy.mf6.ModflowGwfdisv(
        gwf, nlay=1, **mesh.to_disv_kwargs(), idomain=mesh.idomain, xorigin=0.0, yorigin=0.0
    )
    flopy.mf6.ModflowGwfic(gwf, strt=5.0)
    flopy.mf6.ModflowGwfnpf(gwf, icelltype=1, k=1.0)
    rch = flopy.mf6.ModflowGwfrcha(
        gwf,
        recharge={0: 1e-8},
        auxiliary=["CONCENTRATION"],
        aux={0: [np.zeros(ncpl)]},
        pname="RCHA",
    )
    flow_model = SimpleNamespace(
        sim=sim,
        gwf=gwf,
        ims=ims,
        rch=rch,
        solver_mesh=mesh,
        open_water_cell_ids=[],
        nlay=1,
        ncpl=ncpl,
        nper=1,
        sy=np.full((1, ncpl), 0.1),
        model_name="flow",
        exe="mf6",
        modflow_config=_coerce_modflow6_config({"runtime": {"mf6_ims_complexity": complexity}}),
    )
    options = ConcentrationTransportParametersConfig.model_validate(params)
    solver = Modflow6Transport(
        make_model(),
        flow_model,
        model_folder=str(tmp_path),
        model_name="flow",
        suffix_name=_MT_S1,
        options=options.model_dump(),
    )
    solver.pre_processing()
    return solver


# (parameters, zero order decay flag, first order decay flag)
DECAYS = [
    pytest.param({"react_order": 0, "rate_decay": 0.002}, True, False, id="zero order"),
    pytest.param({"react_order": 1, "rate_decay": 0.5}, False, True, id="first order"),
    pytest.param({"react_order": None}, False, False, id="no decay"),
]


@pytest.mark.parametrize(("params", "zero_order", "first_order"), DECAYS)
def test_decay_order(tmp_path, params, zero_order, first_order) -> None:
    solver = build_gwt(tmp_path, params | {"porosity": 0.3})
    assert bool(solver.mst.zero_order_decay.get_data()) is zero_order
    assert bool(solver.mst.first_order_decay.get_data()) is first_order


def test_decay_rate(tmp_path) -> None:
    zero = build_gwt(tmp_path / "zero", {"react_order": 0, "rate_decay": 0.002, "porosity": 0.3})
    np.testing.assert_allclose(np.asarray(zero.mst.decay.get_data()), 0.002)
    none = build_gwt(tmp_path / "none", {"react_order": None, "porosity": 0.3})
    assert none.mst.decay.get_data() is None


@pytest.mark.parametrize("complexity", ["SIMPLE", "MODERATE"])
def test_ims_complexity_follows_the_flow_config(tmp_path, complexity) -> None:
    solver = build_gwt(tmp_path, {"porosity": 0.3}, complexity=complexity)
    assert str(solver.ims.complexity.get_data()).upper() == complexity


def test_concentration_is_saved_once_per_period(tmp_path) -> None:
    # One slice per stress period, at its last step, as the flow saves its head:
    # with ALL a period of five steps wrote five slices and slice k was not period k.
    solver = build_gwt(tmp_path, {"porosity": 0.3})
    records = solver.oc.saverecord.get_data(0)
    saved = {str(row[0]).upper(): str(row[1]).upper() for row in records}
    assert saved["CONCENTRATION"] == "LAST"


def test_recharge_concentration_includes_period_zero() -> None:
    solver = object.__new__(Modflow6Transport)
    solver.sconc_input = 5.0
    solver.model_modflow = SimpleNamespace(nper=1, ncpl=4)
    crch = solver._build_crch()
    assert set(crch) == {0}
    np.testing.assert_allclose(crch[0], [5.0, 5.0, 5.0, 5.0])


def test_sconc_keys_include_period_zero() -> None:
    single = _normalize_sconc_input(0.05, nper=1, nrow=None, ncol=None, ncpl=3, structured=False)
    assert set(single) == {0}
    multi = _normalize_sconc_input(0.05, nper=5, nrow=None, ncol=None, ncpl=3, structured=False)
    assert set(multi) == {1, 2, 3, 4}


def test_period_zero_concentration_warning(monkeypatch) -> None:
    messages: list[str] = []
    monkeypatch.setattr(
        "hydromodpy.solver.modflow_common.runtime_arrays.logger.warning",
        lambda msg, *args: messages.append(str(msg) % args if args else str(msg)),
    )
    _normalize_sconc_input(0.05, nper=1, nrow=None, ncol=None, ncpl=3, structured=False)
    assert len(messages) == 1
    messages.clear()
    _normalize_sconc_input(0.0, nper=1, nrow=None, ncol=None, ncpl=3, structured=False)
    assert messages == []
