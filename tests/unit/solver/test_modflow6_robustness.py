"""WP9 - MF6 numerical robustness defaults and the IMS configuration surface."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from hydromodpy.solver.modflow6.build import (
    guard_newton_linear_acceleration,
    guard_newton_rewet,
    newton_options,
    optional_ims_kwargs,
)
from hydromodpy.solver.modflow6.builders.solver_options import resolve_ims_complexity
from hydromodpy.solver.modflow6.modflow6_config import Modflow6Config, Modflow6RuntimeConfig
from hydromodpy.solver.modflow6.support.steady_initial_conditions import (
    _modflow_config_for_steady_initialization,
)
from hydromodpy.solver.modflow_common.flow_adapter_helpers import _last_percent_discrepancy


def _runtime(**overrides) -> Modflow6RuntimeConfig:
    return Modflow6RuntimeConfig(**overrides)


def _model(runtime: Modflow6RuntimeConfig, *, is_structured: bool = True) -> SimpleNamespace:
    return SimpleNamespace(
        modflow_config=SimpleNamespace(runtime=runtime),
        grid_ctx=SimpleNamespace(solver_mesh=SimpleNamespace(is_structured=is_structured)),
    )


def test_modflow6_ims_complexity_literal_rejects_typo() -> None:
    with pytest.raises(ValidationError):
        Modflow6RuntimeConfig(mf6_ims_complexity="COMPLE")
    for value in ("SIMPLE", "MODERATE", "COMPLEX"):
        assert Modflow6RuntimeConfig(mf6_ims_complexity=value).mf6_ims_complexity == value
    assert Modflow6RuntimeConfig().mf6_ims_complexity == "COMPLEX"


def test_modflow6_vka_must_be_positive() -> None:
    from hydromodpy.solver.modflow6.modflow6_config import Modflow6ProcessSpecificConfig

    for bad in (0.0, -2.0):
        with pytest.raises(ValidationError):
            Modflow6ProcessSpecificConfig(vka=bad)
    assert Modflow6ProcessSpecificConfig(vka=2.0).vka == 2.0


def test_modflow6_newton_enabled_by_default() -> None:
    runtime = Modflow6RuntimeConfig()
    assert runtime.mf6_newton is True
    assert runtime.mf6_newton_under_relaxation is True
    assert newton_options(runtime) == ["NEWTON", "UNDER_RELAXATION"]
    assert newton_options(_runtime(mf6_newton=False)) is None
    assert newton_options(_runtime(mf6_newton=True, mf6_newton_under_relaxation=False)) == [
        "NEWTON"
    ]


def test_modflow6_optional_ims_fields_default_none_and_omitted() -> None:
    runtime = Modflow6RuntimeConfig()
    assert runtime.mf6_inner_rclose is None
    assert runtime.mf6_linear_acceleration is None
    assert runtime.mf6_under_relaxation is None
    assert optional_ims_kwargs(runtime) == {}

    set_runtime = _runtime(
        mf6_inner_rclose=1e-3, mf6_linear_acceleration="BICGSTAB", mf6_under_relaxation="DBD"
    )
    # inner_rclose must go through the rcloserecord record: flopy has no
    # standalone inner_rclose kwarg and rejects it as extraneous.
    assert optional_ims_kwargs(set_runtime) == {
        "rcloserecord": [(1e-3, "")],
        "linear_acceleration": "BICGSTAB",
        "under_relaxation": "DBD",
    }
    with pytest.raises(ValidationError):
        Modflow6RuntimeConfig(mf6_linear_acceleration="XX")
    with pytest.raises(ValidationError):
        Modflow6RuntimeConfig(mf6_under_relaxation="FAST")


def test_modflow6_optional_ims_kwargs_accepted_by_flopy_ims() -> None:
    """Guard the inner_rclose fix at the flopy layer: a bare inner_rclose kwarg
    raises FlopyException, so the kwargs optional_ims_kwargs emits must build a
    real ModflowIms package."""
    import flopy

    set_runtime = _runtime(
        mf6_inner_rclose=1e-3, mf6_linear_acceleration="BICGSTAB", mf6_under_relaxation="DBD"
    )
    sim = flopy.mf6.MFSimulation()
    flopy.mf6.ModflowTdis(sim)
    ims = flopy.mf6.ModflowIms(sim, complexity="COMPLEX", **optional_ims_kwargs(set_runtime))
    record = ims.rcloserecord.get_data()
    values = [float(x) for x in tuple(record[0]) if isinstance(x, (int, float))]
    assert any(abs(v - 1e-3) < 1e-12 for v in values)
    # A bare inner_rclose kwarg is the regression this guards against.
    with pytest.raises(flopy.mf6.mfbase.FlopyException):
        flopy.mf6.ModflowIms(sim, complexity="COMPLEX", inner_rclose=1e-3, pname="ims_bad")


def test_modflow6_newton_cg_conflict_raises() -> None:
    runtime = _runtime(mf6_newton=True, mf6_linear_acceleration="CG")
    with pytest.raises(ValueError, match="E406"):
        guard_newton_linear_acceleration(runtime)
    # BICGSTAB under Newton, CG without Newton, or unset are all fine.
    guard_newton_linear_acceleration(_runtime(mf6_newton=True, mf6_linear_acceleration="BICGSTAB"))
    guard_newton_linear_acceleration(_runtime(mf6_newton=False, mf6_linear_acceleration="CG"))
    guard_newton_linear_acceleration(_runtime(mf6_newton=True))


def test_modflow6_newton_rewet_conflict_raises() -> None:
    runtime = _runtime(mf6_newton=True)
    with pytest.raises(ValueError, match="mutually exclusive"):
        guard_newton_rewet(runtime, rewet_record=["WETFCT", 0.1])
    # Newton without rewet, or rewet without Newton, are both fine.
    guard_newton_rewet(runtime, rewet_record=None)
    guard_newton_rewet(_runtime(mf6_newton=False), rewet_record=["WETFCT", 0.1])


def test_modflow6_complexity_promoted_under_newton() -> None:
    simple_newton = _model(
        _runtime(mf6_ims_complexity="SIMPLE", mf6_newton=True, mf6_enable_xt3d=False)
    )
    assert resolve_ims_complexity(simple_newton) == "MODERATE"
    simple_no_newton = _model(
        _runtime(mf6_ims_complexity="SIMPLE", mf6_newton=False, mf6_enable_xt3d=False)
    )
    assert resolve_ims_complexity(simple_no_newton) == "SIMPLE"
    simple_xt3d = _model(_runtime(mf6_ims_complexity="SIMPLE", mf6_enable_xt3d=True))
    assert resolve_ims_complexity(simple_xt3d) == "COMPLEX"
    moderate = _model(_runtime(mf6_ims_complexity="MODERATE", mf6_newton=True))
    assert resolve_ims_complexity(moderate) == "MODERATE"


def test_modflow6_steady_init_promotes_complexity_under_newton() -> None:
    model = SimpleNamespace(
        modflow_config=Modflow6Config(runtime=Modflow6RuntimeConfig(mf6_ims_complexity="SIMPLE")),
        exe="mf6",
    )
    steady_config = _modflow_config_for_steady_initialization(model)
    assert steady_config.runtime.mf6_newton is True
    steady_model = SimpleNamespace(
        modflow_config=steady_config,
        grid_ctx=SimpleNamespace(solver_mesh=SimpleNamespace(is_structured=True)),
    )
    assert resolve_ims_complexity(steady_model) != "SIMPLE"


def test_modflow6_divergence_message_includes_percent_discrepancy(tmp_path) -> None:
    (tmp_path / "flow.lst").write_text(
        "...\n PERCENT DISCREPANCY =  -3.50\n more\n", encoding="utf-8"
    )
    (tmp_path / "mfsim.lst").write_text("PERCENT DISCREPANCY = 99.0\n", encoding="utf-8")
    # The per-model listing is read; the simulation listing (mfsim.lst) is ignored.
    assert _last_percent_discrepancy(tmp_path) == pytest.approx(-3.5)


def test_modflow6_divergence_message_fallback_when_lst_missing(tmp_path) -> None:
    assert _last_percent_discrepancy(tmp_path) is None


@pytest.mark.regression
@pytest.mark.slow
@pytest.mark.mf6
@pytest.mark.allow_subprocess
def test_modflow6_newton_unconfined_converges_with_default_solver(tmp_path) -> None:
    import flopy

    from hydromodpy.solver.modflow_common.binaries import ensure_solver_binary

    exe = str(ensure_solver_binary("mf6"))
    runtime = Modflow6RuntimeConfig()  # Newton on, COMPLEX, by default.
    sim = flopy.mf6.MFSimulation(sim_name="sim", sim_ws=str(tmp_path), exe_name=exe)
    flopy.mf6.ModflowTdis(sim, nper=1, perioddata=[(1.0, 1, 1.0)], time_units="seconds")
    gwf = flopy.mf6.ModflowGwf(
        sim, modelname="flow", save_flows=True, newtonoptions=newton_options(runtime)
    )
    ims = flopy.mf6.ModflowIms(sim, complexity=runtime.mf6_ims_complexity)
    sim.register_ims_package(ims, [gwf.name])
    # Unconfined: convertible cells, water table well below the top.
    flopy.mf6.ModflowGwfdis(gwf, nlay=1, nrow=1, ncol=10, delr=10.0, delc=10.0, top=10.0, botm=0.0)
    flopy.mf6.ModflowGwfic(gwf, strt=5.0)
    flopy.mf6.ModflowGwfnpf(gwf, icelltype=1, k=1.0)
    flopy.mf6.ModflowGwfrcha(gwf, recharge=1e-3)
    flopy.mf6.ModflowGwfchd(gwf, stress_period_data={0: [[(0, 0, 0), 2.0], [(0, 0, 9), 2.0]]})
    flopy.mf6.ModflowGwfoc(gwf, budget_filerecord="flow.cbc", saverecord=[("BUDGET", "ALL")])
    sim.write_simulation(silent=True)
    success, _ = sim.run_simulation(silent=True)
    # Newton converges this convertible (unconfined) problem with the default solver.
    assert success
    # The listing is readable and reports a water-budget discrepancy.
    assert _last_percent_discrepancy(tmp_path) is not None
