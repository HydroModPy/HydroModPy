"""Optuna profile of the twin calibration validation cases.

Every twin case benchmarks Optuna. The profile keeps the sampler options apart
from the trial budget (max_trials), and a benchmark budget caps it like the other methods.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from validation_cases.calibration.shared.definitions import (
    TwinCalibrationCaseDefinition,
    build_payload,
)
from validation_cases.calibration.shared.runtime import _apply_evaluation_budget
from validation_cases.calibration.twin.steady.dupuit_fixed_head_1d.experiment import (
    STEADY_DUPUIT_TWIN_CASE,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
TWIN_ROOT = REPO_ROOT / "validation_cases" / "calibration" / "twin"


def _twin_cases() -> list[TwinCalibrationCaseDefinition]:
    cases: dict[str, TwinCalibrationCaseDefinition] = {}
    for path in sorted(TWIN_ROOT.rglob("experiment.py")):
        module = importlib.import_module(
            ".".join(path.relative_to(REPO_ROOT).with_suffix("").parts)
        )
        for value in vars(module).values():
            if isinstance(value, TwinCalibrationCaseDefinition):
                cases[value.case_id] = value
    return list(cases.values())


TWIN_CASES = _twin_cases()


def optuna_profile():
    return next(
        profile for profile in STEADY_DUPUIT_TWIN_CASE.method_profiles if profile.name == "optuna"
    )


def test_the_twin_case_discovery_finds_the_cases() -> None:
    assert len(TWIN_CASES) >= 8


@pytest.mark.parametrize("case", TWIN_CASES, ids=[case.case_id for case in TWIN_CASES])
def test_every_calibration_twin_case_benchmarks_optuna(case) -> None:
    assert "optuna" in {profile.name for profile in case.method_profiles}


def test_optuna_validation_profile_uses_top_level_iteration_budget() -> None:
    profile = optuna_profile()

    payload = build_payload(
        STEADY_DUPUIT_TWIN_CASE,
        simulation_config_name="simulation.toml",
        calibration_id="unit_optuna",
        observed_values={"q_east": (1.0,)},
        method_profile=profile,
    )

    calibration = payload["calibration"]
    assert calibration["method"] == "optuna"
    assert calibration["max_trials"] == 32
    assert calibration["seed"] == 7
    assert calibration["method_options"] == {"sampler": "tpe"}


def test_optuna_validation_profile_accepts_common_evaluation_budget() -> None:
    profile = optuna_profile()

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
    assert calibration["max_trials"] == 6
    assert calibration["method_options"] == {"sampler": "tpe"}
