"""Validate PETSc threshold activation on the transient hillslope overflow case."""

from __future__ import annotations

import platform

import numpy as np
import pytest

from validation_cases.numerical.transient.boussinesq_hillslope_recharge_pulse_overflow_1d import (
    run_hillslope_overflow_scenario,
)


def _require_linux_petsc4py() -> None:
    if platform.system().strip().lower() != "linux":
        pytest.skip("Boussinesq PETSc runtime is Linux-only.")
    pytest.importorskip("petsc4py")


@pytest.mark.validation
@pytest.mark.transient
@pytest.mark.slow
@pytest.mark.parametrize(
    ("solver", "forcing_preset"),
    [
        pytest.param("petsc_partition", None, id="petsc_partition"),
        pytest.param("petsc", None, id="petsc_complementarity"),
        pytest.param("petsc", "strong", id="petsc_complementarity_strong"),
        pytest.param("petsc", "alternating", id="petsc_complementarity_alternating"),
    ],
)
def test_hillslope_overflow_petsc_variants_activate_surface_threshold(
    solver: str,
    forcing_preset: str | None,
) -> None:
    _require_linux_petsc4py()

    scenario = run_hillslope_overflow_scenario(
        caller_file=__file__,
        solver=solver,
        forcing_preset=forcing_preset,
    )
    diagnostics = scenario.primary
    summary = dict(diagnostics.runtime_summary)

    assert diagnostics.peak_total_overflow_m3_day > 0.0
    assert diagnostics.peak_active_length_m > 0.0
    assert np.isfinite(diagnostics.onset_day)

    assert summary["surface_threshold_active_any"] is True
    assert int(summary["surface_threshold_peak_active_cells"]) > 0
    assert int(summary["surface_threshold_active_steps"]) > 0
    assert int(summary["surface_threshold_activation_windows"]) > 0
    assert float(summary["surface_threshold_peak_total_m3_day"]) > 0.0
    assert float(summary["surface_threshold_peak_cell_rate_mm_day"]) > float(
        diagnostics.overflow_threshold_mm_day
    )
    assert summary["surface_threshold_first_active_step"] is not None
    assert float(summary["surface_threshold_first_active_day"]) <= float(
        diagnostics.onset_day
    )
    assert float(summary["surface_threshold_peak_total_m3_day"]) == pytest.approx(
        diagnostics.peak_total_overflow_m3_day
    )

    if solver == "petsc":
        assert all(bool(flag) for flag in summary["converged_by_period"])
        assert float(summary["last_residual_norm_inf"]) <= float(
            summary["runtime_tol_residual_inf"]
        )
        if forcing_preset == "alternating":
            assert int(summary["surface_threshold_activation_windows"]) >= 3
            assert int(summary["surface_threshold_state_transitions"]) >= 3
        assert float(summary["surface_complementarity_min_gap_m"]) >= -1.0e-6
        assert float(summary["surface_complementarity_min_rate_m_s"]) >= -1.0e-6
        assert float(summary["surface_complementarity_peak_overlap_m2_s"]) <= 1.0e-8
    else:
        assert "surface_complementarity_min_gap_m" not in summary
