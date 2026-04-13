from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from validation_cases.analytical.steady.dupuit_fixed_head_1d import comparison as module
from validation_cases.analytical.steady.dupuit_fixed_head_1d import runtime_boussinesq as runtime_module
from validation_cases.shared.runtime import ValidationRunResult


def test_dupuit_fixed_head_comparison_routes_solver_petsc_to_boussinesq_runtime(
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}

    def _fake_run_boussinesq_case(
        *,
        caller_file,
        timeout,
        runtime_backend,
        surface_interaction_model=None,
    ):
        captured["caller_file"] = caller_file
        captured["timeout"] = timeout
        captured["runtime_backend"] = runtime_backend
        captured["surface_interaction_model"] = surface_interaction_model
        return SimpleNamespace(solver_name="boussinesq")

    def _fake_build_comparison(*, result, metadata=None, tolerances=None):
        return SimpleNamespace(result=result, metadata=metadata, tolerances=tolerances)

    monkeypatch.setattr(module, "run_boussinesq_dupuit_fixed_head_case", _fake_run_boussinesq_case)
    monkeypatch.setattr(module, "build_dupuit_fixed_head_comparison", _fake_build_comparison)
    monkeypatch.setattr(module, "load_case_metadata", lambda case_dir: {"case_dir": str(case_dir)})
    monkeypatch.setattr(module, "load_case_tolerances", lambda case_dir, solver=None: {"solver": solver})

    comparison = module.run_dupuit_fixed_head_comparison(
        caller_file=Path("dummy_test.py"),
        timeout=123,
        solver="petsc",
    )

    assert captured["runtime_backend"] == "petsc"
    assert captured["surface_interaction_model"] is None
    assert captured["timeout"] == 123
    assert comparison.tolerances == {"solver": "petsc"}


def test_dupuit_fixed_head_comparison_routes_solver_petsc_partition_to_boussinesq_runtime(
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}

    def _fake_run_boussinesq_case(
        *,
        caller_file,
        timeout,
        runtime_backend,
        surface_interaction_model=None,
    ):
        captured["caller_file"] = caller_file
        captured["timeout"] = timeout
        captured["runtime_backend"] = runtime_backend
        captured["surface_interaction_model"] = surface_interaction_model
        return SimpleNamespace(solver_name="boussinesq")

    def _fake_build_comparison(*, result, metadata=None, tolerances=None):
        return SimpleNamespace(result=result, metadata=metadata, tolerances=tolerances)

    monkeypatch.setattr(module, "run_boussinesq_dupuit_fixed_head_case", _fake_run_boussinesq_case)
    monkeypatch.setattr(module, "build_dupuit_fixed_head_comparison", _fake_build_comparison)
    monkeypatch.setattr(module, "load_case_metadata", lambda case_dir: {"case_dir": str(case_dir)})
    monkeypatch.setattr(module, "load_case_tolerances", lambda case_dir, solver=None: {"solver": solver})

    comparison = module.run_dupuit_fixed_head_comparison(
        caller_file=Path("dummy_test.py"),
        timeout=456,
        solver="petsc_partition",
    )

    assert captured["runtime_backend"] == "petsc"
    assert captured["surface_interaction_model"] == "regularized_partition"
    assert captured["timeout"] == 456
    assert comparison.tolerances == {"solver": "petsc_partition"}


def test_dupuit_fixed_head_runtime_reports_requested_petsc_solver_name(monkeypatch) -> None:
    base_result = ValidationRunResult(
        case_dir=Path("."),
        solver_name="boussinesq",
        out_path=Path("."),
        model_ws=Path("."),
        postprocess_dir=Path("."),
        particles_dir=Path("."),
    )

    monkeypatch.setattr(runtime_module, "load_case_metadata", lambda case_dir: {"reference": {
        "aquifer_thickness_m": 10.0,
        "west_head": 10.0,
        "east_head": 5.0,
        "hydraulic_conductivity_m_per_s": 1.0e-4,
    }})
    monkeypatch.setattr(
        runtime_module,
        "run_boussinesq_uniform_strip_case",
        lambda **kwargs: replace(base_result),
    )

    petsc_partition = runtime_module.run_boussinesq_dupuit_fixed_head_case(
        caller_file=Path("dummy_test.py"),
        runtime_backend="petsc",
        surface_interaction_model="regularized_partition",
    )
    petsc = runtime_module.run_boussinesq_dupuit_fixed_head_case(
        caller_file=Path("dummy_test.py"),
        runtime_backend="petsc",
        surface_interaction_model=None,
    )

    assert petsc_partition.solver_name == "petsc_partition"
    assert petsc.solver_name == "petsc"
