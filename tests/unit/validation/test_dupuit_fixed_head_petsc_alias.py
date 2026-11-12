"""Solver names of the Dupuit fixed-head case that map to the PETSc Boussinesq runtime."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from validation_cases.analytical.steady.dupuit_fixed_head_1d import comparison as module
from validation_cases.analytical.steady.dupuit_fixed_head_1d import (
    runtime_boussinesq as runtime_module,
)
from validation_cases.shared.runtime import ValidationRunResult

SURFACE_MODELS = [
    pytest.param("petsc", 123, "complementarity", id="petsc"),
    pytest.param("petsc_partition", 456, "regularized_partition", id="petsc partition"),
]


@pytest.mark.parametrize(("solver", "timeout", "surface_model"), SURFACE_MODELS)
def test_comparison_routes_solver_to_boussinesq_runtime(
    monkeypatch, solver, timeout, surface_model
):
    captured = {}

    def fake_run_case(
        *,
        caller_file,
        timeout,
        runtime_backend,
        surface_interaction_model=None,
        public_solver_label="boussinesq",
    ):
        captured.update(
            timeout=timeout,
            runtime_backend=runtime_backend,
            surface_interaction_model=surface_interaction_model,
            public_solver_label=public_solver_label,
        )
        return SimpleNamespace(solver_name="boussinesq")

    def fake_build_comparison(*, result, metadata=None, tolerances=None):
        return SimpleNamespace(result=result, metadata=metadata, tolerances=tolerances)

    monkeypatch.setattr(module, "run_boussinesq_dupuit_fixed_head_case", fake_run_case)
    monkeypatch.setattr(module, "build_dupuit_fixed_head_comparison", fake_build_comparison)
    monkeypatch.setattr(module, "load_case_metadata", lambda case_dir: {"case_dir": str(case_dir)})
    monkeypatch.setattr(
        module, "load_case_tolerances", lambda case_dir, solver=None: {"solver": solver}
    )

    comparison = module.run_dupuit_fixed_head_comparison(
        caller_file=Path("dummy_test.py"), timeout=timeout, solver=solver
    )

    assert captured == {
        "timeout": timeout,
        "runtime_backend": "petsc",
        "surface_interaction_model": surface_model,
        "public_solver_label": solver,
    }
    assert comparison.tolerances == {"solver": solver}


def test_runtime_reports_the_requested_solver_name(monkeypatch):
    base_result = ValidationRunResult(
        case_dir=Path("."),
        solver_name="boussinesq",
        out_path=Path("."),
        model_ws=Path("."),
        postprocess_dir=Path("."),
        particles_dir=Path("."),
    )
    metadata = {
        "reference": {
            "aquifer_thickness_m": 10.0,
            "west_head": 10.0,
            "east_head": 5.0,
            "hydraulic_conductivity_m_per_s": 1.0e-4,
        }
    }
    monkeypatch.setattr(runtime_module, "load_case_metadata", lambda case_dir: metadata)
    monkeypatch.setattr(
        runtime_module, "run_boussinesq_uniform_strip_case", lambda **kwargs: replace(base_result)
    )

    partition = runtime_module.run_boussinesq_dupuit_fixed_head_case(
        caller_file=Path("dummy_test.py"),
        runtime_backend="petsc",
        surface_interaction_model="regularized_partition",
        public_solver_label="petsc_partition",
    )
    petsc = runtime_module.run_boussinesq_dupuit_fixed_head_case(
        caller_file=Path("dummy_test.py"),
        runtime_backend="petsc",
        surface_interaction_model="complementarity",
        public_solver_label="petsc",
    )

    assert partition.solver_name == "petsc_partition"
    assert petsc.solver_name == "petsc"
