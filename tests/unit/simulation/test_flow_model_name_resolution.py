"""Unit tests for flow model-name resolution helpers."""

from types import SimpleNamespace

from hydromodpy.simulation.adapters.flow.modflow_common import (
    build_preprocess_options,
    resolve_base_model_name,
    resolve_run_model_name,
)
from hydromodpy.simulation.planning.plan import ProcessRun, RunContext, SimulationPlan


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
