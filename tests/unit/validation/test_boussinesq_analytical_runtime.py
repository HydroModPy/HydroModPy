"""Unit tests for analytical Boussinesq runtime defaults."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from hydromodpy.model.flow import Flow
from hydromodpy.model.flow_config import FlowConfig
from hydromodpy.solver.base.plan import RunSlot
from hydromodpy.solver.boussinesq.options import BoussinesqOptions
from validation_cases.shared import boussinesq_analytical_runtime as runtime
from validation_cases.shared.boussinesq_analytical_runtime import (
    apply_analytical_boussinesq_runtime_defaults,
    boussinesq_variant_flow_section,
    boussinesq_variant_options,
    solve_boussinesq_bundle,
)
from validation_cases.shared.boussinesq_piecewise_strip import (
    write_piecewise_strip_launcher_config,
)


def test_analytical_boussinesq_defaults_fill_steady_petsc_vi() -> None:
    runtime = apply_analytical_boussinesq_runtime_defaults({}, flow_regime="steady")

    assert runtime["backend"] == "petsc"
    assert runtime["surface_interaction_model"] == "vi_obstacle"


def test_analytical_boussinesq_defaults_fill_transient_petsc_ts_vi() -> None:
    runtime = apply_analytical_boussinesq_runtime_defaults({}, flow_regime="transient")

    assert runtime["backend"] == "petsc"
    assert runtime["surface_interaction_model"] == "ts_vi_obstacle"
    assert runtime["ts_vi_steps_per_period"] == 4
    assert runtime["ts_vi_type"] == "beuler"


def test_analytical_boussinesq_defaults_keep_explicit_petsc_surface_model() -> None:
    runtime = apply_analytical_boussinesq_runtime_defaults(
        {"backend": "petsc", "surface_interaction_model": "complementarity"},
        flow_regime="steady",
    )

    assert runtime["backend"] == "petsc"
    assert runtime["surface_interaction_model"] == "complementarity"


def test_analytical_boussinesq_defaults_force_replaces_explicit_model() -> None:
    runtime = apply_analytical_boussinesq_runtime_defaults(
        {"backend": "petsc", "surface_interaction_model": "complementarity"},
        flow_regime="steady",
        force=True,
    )

    assert runtime["backend"] == "petsc"
    assert runtime["surface_interaction_model"] == "vi_obstacle"


def test_a_variant_flow_section_holds_no_runtime_key() -> None:
    section = boussinesq_variant_flow_section(
        {"flow_regime": "steady", "runtime": {"backend": "local"}, "runtime_max_iterations": 5},
        flow_regime="steady",
    )

    assert section == {"flow_regime": "steady"}


def test_a_transient_variant_flow_section_starts_from_its_initial_condition() -> None:
    section = boussinesq_variant_flow_section({"flow_regime": "transient"})

    assert section["first_period_steady"] is False


@pytest.mark.parametrize(
    ("solver", "written", "backend", "model"),
    [
        pytest.param("boussinesq", None, "petsc", "vi_obstacle", id="analytical defaults"),
        pytest.param("boussinesq", {"backend": "local"}, "local", "vi_obstacle", id="case value"),
        pytest.param("boussinesq_local", None, "auto", None, id="library default engine"),
        pytest.param(
            "boussinesq_local", {"backend": "petsc"}, "auto", None, id="default engine drops case"
        ),
    ],
)
def test_a_variant_gets_the_settings_of_its_label(
    solver: str, written: dict | None, backend: str, model: str | None
) -> None:
    options = boussinesq_variant_options(flow_regime="steady", solver=solver, written=written)

    assert isinstance(options, BoussinesqOptions)
    assert options.backend == backend
    expected = model or BoussinesqOptions.model_fields["surface_interaction_model"].default
    assert options.surface_interaction_model == expected


def test_a_variant_reads_the_table_of_the_case_config(tmp_path) -> None:
    (tmp_path / "config_boussinesq.toml").write_text(
        "[solver.boussinesq]\nmax_iterations = 80\ntol_residual_inf = 1e-9\n", encoding="utf-8"
    )

    petsc = boussinesq_variant_options(
        flow_regime="steady",
        solver="boussinesq",
        case_dir=tmp_path,
        config_name="config_boussinesq.toml",
    )
    local = boussinesq_variant_options(
        flow_regime="steady",
        solver="boussinesq_local",
        case_dir=tmp_path,
        config_name="config_boussinesq.toml",
    )

    assert (petsc.backend, petsc.max_iterations, petsc.tol_residual_inf) == ("petsc", 80, 1e-9)
    assert (local.backend, local.max_iterations, local.tol_residual_inf) == ("auto", 80, 1e-9)


def test_piecewise_launcher_config_can_preserve_explicit_runtime_defaults(tmp_path) -> None:
    config_path = write_piecewise_strip_launcher_config(
        tmp_path / "run_petsc.toml",
        run_id="petsc_regression",
        process_id="flow_main",
        simulation_name="PETSc regression",
        simulation_description="Explicit PETSc backend fixture",
        bundle_dir=tmp_path / "mesh_bundle",
        initial_head_m=6.0,
        runtime_backend="petsc",
        surface_interaction_model="vi_obstacle",
        apply_runtime_defaults=False,
    )

    payload = tomllib.loads(config_path.read_text(encoding="utf-8"))

    assert payload["solver"]["boussinesq"]["backend"] == "petsc"
    assert payload["solver"]["boussinesq"]["surface_interaction_model"] == "vi_obstacle"
    assert "runtime" not in payload["flow"]


def test_a_bundle_run_goes_through_the_runner_function_with_the_bundle_as_its_mesh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple] = []
    monkeypatch.setattr(runtime, "solve_one", lambda *args: calls.append(args) or "solved")
    bundle_dir = tmp_path / "mesh_bundle"

    result = solve_boussinesq_bundle(
        flow=Flow(FlowConfig.model_validate({"flow_regime": "steady", "ic": {"kind": "bottom"}})),
        bundle_dir=bundle_dir,
        simulations_folder=tmp_path / "sims",
        plan_name="demo",
        plan_description="demo run",
        options=BoussinesqOptions(backend="petsc"),
    )

    assert result == "solved"
    ((adapter, model, options, slot, ctx),) = calls
    assert type(adapter).__name__ == "BoussinesqFlowAdapter"
    assert model.geometry.cells is None
    assert options.exchange_mesh == bundle_dir
    assert options.backend == "petsc"
    assert slot == RunSlot(folder=tmp_path / "sims", name="flow_validation__boussinesq")
    assert ctx.plan.name == "demo"
    assert ctx.run.id == "flow_validation::boussinesq"


def test_a_bundle_run_without_options_takes_the_defaults_of_the_table(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple] = []
    monkeypatch.setattr(runtime, "solve_one", lambda *args: calls.append(args))

    solve_boussinesq_bundle(
        flow=Flow(FlowConfig.model_validate({"ic": {"kind": "bottom"}})),
        bundle_dir=tmp_path / "bundle",
        simulations_folder=tmp_path,
        plan_name="demo",
        plan_description="demo run",
    )

    options = calls[0][2]
    assert options == BoussinesqOptions(exchange_mesh=tmp_path / "bundle")
