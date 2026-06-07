"""Validation-case coverage for the Optuna calibration profile."""

from __future__ import annotations

from tools.doc_gallery.calibration_case_registry import build_calibration_case_records
from validation_cases.calibration.shared.definitions import build_payload
from validation_cases.calibration.shared.runtime import _apply_evaluation_budget
from validation_cases.calibration.twin.steady.dupuit_fixed_head_1d.experiment import (
    STEADY_DUPUIT_TWIN_CASE,
)


def test_curated_calibration_gallery_cases_include_optuna() -> None:
    """The generated calibration HTML pages should expose Optuna as a benchmark method."""
    records = build_calibration_case_records()

    assert records
    for record in records:
        assert "optuna" in record.metadata["method_names"]


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
