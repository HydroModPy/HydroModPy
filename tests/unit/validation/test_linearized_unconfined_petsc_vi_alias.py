"""The ``petsc_vi_obstacle`` solver name of the linearized unconfined step cases (heads in m).

It runs the PETSc backend with the VI obstacle surface model and 4 fixed sub-steps per period.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from validation_cases.analytical.transient.linearized_unconfined_boundary_step_1d import (
    comparison as boundary_comparison,
)
from validation_cases.analytical.transient.linearized_unconfined_boundary_step_1d import (
    runtime_boussinesq as boundary_runtime,
)
from validation_cases.analytical.transient.linearized_unconfined_recharge_step_1d import (
    comparison as recharge_comparison,
)
from validation_cases.analytical.transient.linearized_unconfined_recharge_step_1d import (
    runtime_boussinesq as recharge_runtime,
)

COMPARISONS = [
    pytest.param(
        recharge_comparison,
        "run_boussinesq_linearized_unconfined_recharge_step_case",
        "build_linearized_unconfined_recharge_step_comparison",
        "run_linearized_unconfined_recharge_step_comparison",
        id="recharge step",
    ),
    pytest.param(
        boundary_comparison,
        "run_boussinesq_linearized_unconfined_boundary_step_case",
        "build_linearized_unconfined_boundary_step_comparison",
        "run_linearized_unconfined_boundary_step_comparison",
        id="boundary step",
    ),
]


@pytest.mark.parametrize(("module", "run_name", "build_name", "compare_name"), COMPARISONS)
def test_alias_routes_to_vi_obstacle(monkeypatch, module, run_name, build_name, compare_name):
    captured = {}

    def fake_run_case(
        *,
        caller_file,
        timeout,
        runtime_backend,
        surface_interaction_model,
        public_solver_label,
    ):
        captured.update(
            runtime_backend=runtime_backend,
            surface_interaction_model=surface_interaction_model,
            public_solver_label=public_solver_label,
        )
        return SimpleNamespace(solver_name=public_solver_label)

    def fake_build_comparison(*, result, solver=None):
        captured["comparison_solver"] = solver
        return SimpleNamespace(result=result)

    monkeypatch.setattr(module, run_name, fake_run_case)
    monkeypatch.setattr(module, build_name, fake_build_comparison)

    comparison = getattr(module, compare_name)(
        caller_file=Path("dummy_test.py"), timeout=123, solver="petsc_vi_obstacle"
    )

    assert comparison.result.solver_name == "petsc_vi_obstacle"
    assert captured == {
        "runtime_backend": "petsc",
        "surface_interaction_model": "vi_obstacle",
        "public_solver_label": "petsc_vi_obstacle",
        "comparison_solver": "petsc_vi_obstacle",
    }


TIME = {"dt_seconds": 43200.0}  # 12 h
OUTPUT = {"expected_periods": 2}

RUNTIMES = [
    pytest.param(
        recharge_runtime,
        "run_boussinesq_linearized_unconfined_recharge_step_case",
        {
            "reference": {
                "base_head_m": 10.0,
                "reference_saturated_thickness_m": 10.0,
                "recharge_mm_day": 10.0,
                "hydraulic_conductivity_m_per_s": 1.0e-4,
                "specific_yield": 0.1,
            },
            "output": OUTPUT,
            "time": TIME,
        },
        id="recharge step",
    ),
    pytest.param(
        boundary_runtime,
        "run_boussinesq_linearized_unconfined_boundary_step_case",
        {
            "reference": {
                "base_head_m": 10.0,
                "west_head_m": 10.1,
                "reference_saturated_thickness_m": 10.0,
                "hydraulic_conductivity_m_per_s": 1.0e-4,
                "specific_yield": 0.1,
            },
            "output": OUTPUT,
            "time": TIME,
        },
        id="boundary step",
    ),
]


@pytest.mark.parametrize(("module", "run_name", "metadata"), RUNTIMES)
def test_runtime_sets_fixed_vi_substeps(monkeypatch, module, run_name, metadata):
    captured = {}

    def fake_run_uniform_strip_case(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(solver_name=kwargs["public_solver_label"])

    monkeypatch.setattr(module, "load_case_metadata", lambda case_dir: metadata)
    monkeypatch.setattr(
        module,
        "run_boussinesq_transient_uniform_strip_case",
        fake_run_uniform_strip_case,
    )

    result = getattr(module, run_name)(
        caller_file=Path("dummy_test.py"),
        runtime_backend="petsc",
        surface_interaction_model="vi_obstacle",
        public_solver_label="petsc_vi_obstacle",
    )

    settings = dict(captured["boussinesq_settings"])
    assert result.solver_name == "petsc_vi_obstacle"
    assert "runtime" not in captured["flow_section"]
    assert settings["backend"] == "petsc"
    assert settings["surface_interaction_model"] == "vi_obstacle"
    assert settings["vi_substeps_per_period"] == 4
    assert settings["vi_substep_on_failure"] is False
    assert "ts_vi_steps_per_period" not in settings
    assert "ts_vi_type" not in settings
