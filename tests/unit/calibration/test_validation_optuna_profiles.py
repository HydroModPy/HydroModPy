"""Validation-case coverage for the Optuna calibration profile."""

from __future__ import annotations

import pytest

from validation_cases.calibration.shared.definitions import build_payload
from validation_cases.calibration.shared.runtime import _apply_evaluation_budget
from validation_cases.calibration.twin.steady.boussinesq_fixed_head_piecewise_k_1d.experiment import (
    PIECEWISE_K_TWIN_CASE,
)
from validation_cases.calibration.twin.steady.dupuit_fixed_head_1d.experiment import (
    STEADY_DUPUIT_POSTERIOR_TWIN_CASE,
    STEADY_DUPUIT_TWIN_CASE,
)
from validation_cases.calibration.twin.transient.linearized_unconfined_recharge_step_1d.experiment import (
    TRANSIENT_RECHARGE_STEP_FLUX_ONLY_NOISY_TWIN_CASE,
    TRANSIENT_RECHARGE_STEP_TWIN_CASE,
)


@pytest.mark.parametrize(
    "case",
    [
        STEADY_DUPUIT_TWIN_CASE,
        STEADY_DUPUIT_POSTERIOR_TWIN_CASE,
        TRANSIENT_RECHARGE_STEP_TWIN_CASE,
        TRANSIENT_RECHARGE_STEP_FLUX_ONLY_NOISY_TWIN_CASE,
        PIECEWISE_K_TWIN_CASE,
    ],
    ids=["dupuit", "dupuit_posterior", "recharge_step", "recharge_step_noisy", "piecewise_k"],
)
def test_every_calibration_twin_case_benchmarks_optuna(case) -> None:
    """Each calibration twin case runs Optuna among its methods."""
    assert "optuna" in {profile.name for profile in case.method_profiles}


def test_optuna_validation_profile_uses_top_level_iteration_budget() -> None:
    """Optuna profiles keep sampler kwargs separate from the calibration loop budget."""
    profile = next(
        profile for profile in STEADY_DUPUIT_TWIN_CASE.method_profiles if profile.name == "optuna"
    )

    payload = build_payload(
        STEADY_DUPUIT_TWIN_CASE,
        simulation_config_name="simulation.toml",
        calibration_id="unit_optuna",
        observed_values={"q_east": (1.0,)},
        method_profile=profile,
    )

    calibration = payload["calibration"]
    assert calibration["method"] == "optuna"
    assert calibration["max_iter"] == 32
    assert calibration["seed"] == 7
    assert calibration["optimizer_kwargs"] == {"sampler": "tpe"}


def test_optuna_validation_profile_accepts_common_evaluation_budget() -> None:
    """Benchmark budget capping works for Optuna like the other profiled methods."""
    profile = next(
        profile for profile in STEADY_DUPUIT_TWIN_CASE.method_profiles if profile.name == "optuna"
    )

    capped = _apply_evaluation_budget(
        profile,
        n_parameters=len(STEADY_DUPUIT_TWIN_CASE.truth_params),
        evaluation_budget=6,
    )
    payload = build_payload(
        STEADY_DUPUIT_TWIN_CASE,
        simulation_config_name="simulation.toml",
        calibration_id="unit_optuna_budget",
        observed_values={"q_east": (1.0,)},
        method_profile=capped,
    )

    calibration = payload["calibration"]
    assert calibration["max_iter"] == 6
    assert calibration["optimizer_kwargs"] == {"sampler": "tpe"}
