"""Unit tests for flow model-name resolution helpers."""

from types import SimpleNamespace

from hydromodpy.simulation.planning.plan import ProcessRun, RunContext, SimulationPlan
from hydromodpy.solver.modflow6.build import mf6_output_name, mf6_safe_name
from hydromodpy.solver.modflow_common.flow_adapter_helpers import (
    build_preprocess_options,
    resolve_base_model_name,
    resolve_run_model_name,
)


def test_resolve_base_model_name_prefers_run_id() -> None:
    setup = SimpleNamespace(run_id="launcher_name")
    assert resolve_base_model_name(setup) == "launcher_name"


def test_resolve_base_model_name_ignores_legacy_model_name() -> None:
    setup = SimpleNamespace(model_name="legacy_name")
    assert resolve_base_model_name(setup) == "default"


def test_resolve_base_model_name_defaults_when_blank() -> None:
    setup = SimpleNamespace(run_id="")
    assert resolve_base_model_name(setup) == "default"


def test_resolve_base_model_name_defaults_when_missing() -> None:
    setup = SimpleNamespace()
    assert resolve_base_model_name(setup) == "default"


def test_build_preprocess_options_returns_defaults() -> None:
    """build_preprocess_options uses ModflowPreprocessOptions defaults directly.

    settings.py is deprecated; options are sourced from FlowConfig /
    ModflowPreprocessOptions defaults instead.
    """
    from hydromodpy.solver.modflow_nwt import ModflowPreprocessOptions

    state = SimpleNamespace(setup=SimpleNamespace())
    options = build_preprocess_options(state)

    defaults = ModflowPreprocessOptions()
    assert options.box is defaults.box
    assert options.sink_fill is defaults.sink_fill
    assert options.check_grid is defaults.check_grid


def test_resolve_run_model_name_prefers_runtime_override() -> None:
    plan = SimulationPlan(
        name="demo",
        description="demo",
        runs=(
            ProcessRun(
                id="flow_main::modflow6",
                process_id="flow_main",
                process_type="flow",
                solver="modflow6",
            ),
        ),
    )
    ctx = RunContext(
        plan=plan,
        run=plan.runs[0],
        state=SimpleNamespace(
            setup=SimpleNamespace(
                run_id="candidate_run_id",
                flow_runtime_overrides={"model_name_override": "stable_runtime_model"},
            )
        ),
    )

    assert resolve_run_model_name(ctx) == "stable_runtime_model"


def test_mf6_output_name_shortens_long_windows_paths(monkeypatch) -> None:
    import hydromodpy.solver.modflow6.build as build_module

    long_name = "natural_mesh_10km2_transient_pulse_mf6_vs_bouss__mf6_ref"
    safe_name = mf6_safe_name(long_name)
    long_root = "C:\\" + "\\".join(["hydromodpy_regression_outputs"] * 8)
    model = SimpleNamespace(
        full_path=long_root,
        model_name=long_name,
        model_name_mf6=safe_name,
    )

    monkeypatch.setattr(build_module.os, "name", "nt")

    assert mf6_output_name(model) == safe_name


def test_mf6_output_name_preserves_short_windows_paths(monkeypatch) -> None:
    import hydromodpy.solver.modflow6.build as build_module

    model = SimpleNamespace(
        full_path="C:\\hmp\\scratch",
        model_name="demo",
        model_name_mf6="demo",
    )

    monkeypatch.setattr(build_module.os, "name", "nt")

    assert mf6_output_name(model) == "demo"
