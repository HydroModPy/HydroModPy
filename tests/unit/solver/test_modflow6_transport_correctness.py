"""WP7 - MODFLOW 6 GWT transport correctness (decay, scheme, IMS, steady sp0)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import flopy
import numpy as np
import pytest

from hydromodpy.physics.transport.transport import Transport
from hydromodpy.physics.transport.transport_config import ConcentrationTransportParametersConfig
from hydromodpy.solver.modflow6.modflow6_config import _coerce_modflow6_config
from hydromodpy.solver.modflow6.transport import Modflow6Transport
from hydromodpy.solver.modflow_common.runtime_arrays import _normalize_sconc_input


def _build_gwt(tmp_path: Path, params: dict, *, complexity: str = "COMPLEX") -> Modflow6Transport:
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
    from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh
    from hydromodpy.spatial.mesh import CellBlock, CellType, HydroMesh

    mesh = SolverMesh(
        planar_mesh=HydroMesh(
            vertices=vertices, cell_blocks=(CellBlock(CellType.QUADRILATERAL, conn),)
        ),
        top=np.full(ncpl, 10.0),
        botm=np.zeros((1, ncpl)),
        inactive_mask=np.zeros((1, ncpl), dtype=bool),
    )
    flopy.mf6.ModflowGwfdisv(
        gwf, nlay=1, **mesh.to_disv_kwargs(), idomain=mesh.idomain(), xorigin=0.0, yorigin=0.0
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
        nlay=1,
        ncpl=ncpl,
        nper=1,
        sy=np.full((1, ncpl), 0.1),
        model_name="flow",
        exe="mf6",
        modflow_config=_coerce_modflow6_config({"runtime": {"mf6_ims_complexity": complexity}}),
    )
    transport = Transport({"modflow6gwt": {"parameters": params}})
    solver = Modflow6Transport(SimpleNamespace(), transport, flow_model, str(tmp_path), "flow")
    solver.pre_processing()
    return solver


def test_react_order_literal_rejects_invalid_values() -> None:
    for bad in (2, -1):
        with pytest.raises(Exception):
            ConcentrationTransportParametersConfig(react_order=bad)
    for good in (None, 0, 1):
        assert ConcentrationTransportParametersConfig(react_order=good).react_order == good
    with pytest.raises(Exception):
        ConcentrationTransportParametersConfig(scheme="TVDX")
    for scheme in ("upstream", "central", "TVD"):
        assert ConcentrationTransportParametersConfig(scheme=scheme).scheme == scheme


def test_mst_zero_order_decay_activates(tmp_path) -> None:
    solver = _build_gwt(tmp_path / "zero", {"react_order": 0, "rate_decay": 0.002, "porosity": 0.3})
    assert bool(solver.mst.zero_order_decay.get_data()) is True
    assert not solver.mst.first_order_decay.get_data()
    np.testing.assert_allclose(np.asarray(solver.mst.decay.get_data()), 0.002)

    first = _build_gwt(tmp_path / "first", {"react_order": 1, "rate_decay": 0.5, "porosity": 0.3})
    assert bool(first.mst.first_order_decay.get_data()) is True
    assert not first.mst.zero_order_decay.get_data()

    none = _build_gwt(tmp_path / "none", {"react_order": None, "porosity": 0.3})
    assert not none.mst.zero_order_decay.get_data()
    assert not none.mst.first_order_decay.get_data()
    assert none.mst.decay.get_data() is None


def test_advection_scheme_passthrough(tmp_path) -> None:
    tvd = _build_gwt(tmp_path / "tvd", {"scheme": "TVD", "porosity": 0.3})
    assert tvd.adv.scheme.get_data() == "tvd"
    central = _build_gwt(tmp_path / "central", {"scheme": "central", "porosity": 0.3})
    assert central.adv.scheme.get_data() == "central"
    default = _build_gwt(tmp_path / "default", {"porosity": 0.3})
    assert default.adv.scheme.get_data() == "upstream"


def test_gwt_ims_complexity_follows_flow_config(tmp_path) -> None:
    simple = _build_gwt(tmp_path / "simple", {"porosity": 0.3}, complexity="SIMPLE")
    assert str(simple.ims.complexity.get_data()).upper() == "SIMPLE"
    moderate = _build_gwt(tmp_path / "moderate", {"porosity": 0.3}, complexity="MODERATE")
    assert str(moderate.ims.complexity.get_data()).upper() == "MODERATE"


def test_build_crch_includes_sp0_when_fully_steady() -> None:
    solver = object.__new__(Modflow6Transport)
    solver.sconc_input = 5.0
    solver.model_modflow = SimpleNamespace(nper=1, ncpl=4)
    crch = solver._build_crch()
    assert set(crch) == {0}
    np.testing.assert_allclose(crch[0], [5.0, 5.0, 5.0, 5.0])


def test_normalize_sconc_input_keys_include_period_zero_single_period() -> None:
    single = _normalize_sconc_input(0.05, nper=1, nrow=None, ncol=None, ncpl=3, structured=False)
    assert set(single) == {0}
    multi = _normalize_sconc_input(0.05, nper=5, nrow=None, ncol=None, ncpl=3, structured=False)
    assert set(multi) == {1, 2, 3, 4}


def test_sp0_recharge_concentration_warning_emitted(monkeypatch) -> None:
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
