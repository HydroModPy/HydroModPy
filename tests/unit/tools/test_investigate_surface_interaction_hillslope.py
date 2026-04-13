from __future__ import annotations

import numpy as np

from tools.investigate_surface_interaction_hillslope import (
    InvestigationResult,
    ScenarioSpec,
    _locked_length_from_toe,
    _pairwise_rows,
)


def _dummy_result(
    *,
    scenario: ScenarioSpec,
    solver: str,
    x: np.ndarray,
    profile: np.ndarray,
) -> InvestigationResult:
    zeros = np.zeros_like(profile, dtype=float)
    return InvestigationResult(
        scenario=scenario,
        solver=solver,
        out_path=None,  # type: ignore[arg-type]
        postprocess_dir=None,  # type: ignore[arg-type]
        x=np.asarray(x, dtype=float),
        topography_profile=zeros,
        analytical_profile=zeros,
        numerical_profile=np.asarray(profile, dtype=float),
        residual_profile=zeros,
        clearance_profile=zeros,
        rms_error=0.0,
        max_error=0.0,
        row_spread=0.0,
        min_clearance_m=0.0,
        mean_clearance_m=0.0,
        max_clearance_m=0.0,
        surface_lock_fraction=0.0,
        below_surface_fraction=0.0,
        locked_length_from_toe_m=0.0,
    )


def test_locked_length_from_toe_uses_contiguous_toe_segment() -> None:
    x = np.asarray([0.5, 1.5, 2.5, 3.5], dtype=float)
    clearance = np.asarray([0.12, 0.01, 0.0, -0.015], dtype=float)

    length = _locked_length_from_toe(x, clearance, tol_m=0.02)

    assert length == 3.0


def test_pairwise_rows_interpolates_to_common_support() -> None:
    scenario = ScenarioSpec(
        scenario_id="demo",
        label="Demo",
        head_offset_m=0.25,
        drainage_conductance_m2_per_s=1.0e-5,
    )
    left = _dummy_result(
        scenario=scenario,
        solver="modflownwt",
        x=np.asarray([0.0, 1.0, 2.0], dtype=float),
        profile=np.asarray([0.0, 1.0, 2.0], dtype=float),
    )
    right = _dummy_result(
        scenario=scenario,
        solver="boussinesq",
        x=np.asarray([0.0, 0.5, 1.0, 1.5, 2.0], dtype=float),
        profile=np.asarray([0.0, 0.5, 1.0, 1.5, 2.0], dtype=float),
    )

    rows = _pairwise_rows([left, right])

    assert len(rows) == 1
    assert rows[0]["pairwise_profile_rmse_m"] == 0.0
    assert rows[0]["pairwise_max_abs_error_m"] == 0.0
    assert rows[0]["pairwise_mean_abs_error_m"] == 0.0
