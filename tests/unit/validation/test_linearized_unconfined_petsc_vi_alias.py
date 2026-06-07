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


@pytest.mark.parametrize(
    "module,run_name",
    [
        (
            recharge_comparison,
            "run_boussinesq_linearized_unconfined_recharge_step_case",
        ),
        (
            boundary_comparison,
            "run_boussinesq_linearized_unconfined_boundary_step_case",
        ),
    ],
)
def test_linearized_unconfined_petsc_vi_alias_routes_to_vi_obstacle(
    monkeypatch, module, run_name: str
) -> None:
    captured: dict[str, object] = {}

    def _fake_run_boussinesq_case(
        *,
        caller_file,
        timeout,
        runtime_backend,
        surface_interaction_model,
        public_solver_label,
    ):
        captured["caller_file"] = caller_file
        captured["timeout"] = timeout
        captured["runtime_backend"] = runtime_backend
        captured["surface_interaction_model"] = surface_interaction_model
        captured["public_solver_label"] = public_solver_label
        return SimpleNamespace(solver_name=public_solver_label)

    def _fake_build_comparison(*, result, solver=None):
        captured["comparison_solver"] = solver
        return SimpleNamespace(result=result)

    monkeypatch.setattr(module, run_name, _fake_run_boussinesq_case)
    if module is recharge_comparison:
        monkeypatch.setattr(
            module,
            "build_linearized_unconfined_recharge_step_comparison",
            _fake_build_comparison,
        )
        comparison = module.run_linearized_unconfined_recharge_step_comparison(
            caller_file=Path("dummy_test.py"),
            timeout=123,
            solver="petsc_vi_obstacle",
        )
    else:
        monkeypatch.setattr(
            module,
            "build_linearized_unconfined_boundary_step_comparison",
            _fake_build_comparison,
        )
        comparison = module.run_linearized_unconfined_boundary_step_comparison(
            caller_file=Path("dummy_test.py"),
            timeout=123,
            solver="petsc_vi_obstacle",
        )

    assert comparison.result.solver_name == "petsc_vi_obstacle"
    assert captured["runtime_backend"] == "petsc"
    assert captured["surface_interaction_model"] == "vi_obstacle"
    assert captured["public_solver_label"] == "petsc_vi_obstacle"
    assert captured["comparison_solver"] == "petsc_vi_obstacle"


@pytest.mark.parametrize(
    "module,run_name,metadata",
    [
        (
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
                "output": {"expected_periods": 2},
                "time": {"dt_seconds": 43200.0},
            },
        ),
        (
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
                "output": {"expected_periods": 2},
                "time": {"dt_seconds": 43200.0},
            },
        ),
    ],
)
def test_linearized_unconfined_petsc_vi_runtime_sets_fixed_vi_substeps(
    monkeypatch, module, run_name: str, metadata: dict
) -> None:
    captured: dict[str, object] = {}

    def _fake_run_uniform_strip_case(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(solver_name=kwargs["public_solver_label"])

    monkeypatch.setattr(module, "load_case_metadata", lambda case_dir: metadata)
    monkeypatch.setattr(
        module,
        "run_boussinesq_transient_uniform_strip_case",
        _fake_run_uniform_strip_case,
    )

    result = getattr(module, run_name)(
        caller_file=Path("dummy_test.py"),
        runtime_backend="petsc",
        surface_interaction_model="vi_obstacle",
        public_solver_label="petsc_vi_obstacle",
    )

    flow_section = dict(captured["flow_section"])
    assert result.solver_name == "petsc_vi_obstacle"
    assert flow_section["runtime_backend"] == "petsc"
    assert flow_section["surface_interaction_model"] == "vi_obstacle"
    assert flow_section["vi_substeps_per_period"] == 4
    assert flow_section["vi_substep_on_failure"] is False
    assert "ts_vi_steps_per_period" not in flow_section
    assert "ts_vi_type" not in flow_section
