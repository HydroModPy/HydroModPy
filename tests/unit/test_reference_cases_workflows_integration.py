"""Light integration tests for reference-case calibration workflows."""

from __future__ import annotations

import pytest

from reference_cases.calibration_results import CalibrationResults
from reference_cases.recession_brutsaert.example_calibration_coarse_sand import (
    build_noisy_coarse_sand_chronicle,
    calibrate_k_sy,
)
from reference_cases.reservoir.calibration_case import (
    calibrate_reservoir_model,
    resolve_model_name,
)
from reference_cases.reservoir.reference_chronicle import build_noisy_reservoir_chronicle


def _reservoir_base_config(*, method):
    return {
        "chronicle": {
            "n_days": 40,
            "start_year": 2000,
            "target_annual_precip_mm": 400.0,
            "precip_seed": 7,
            "runoff_coeff": 0.20,
            "losses_mm_day": 0.8,
            "losses_months": [4, 5, 6, 7, 8, 9],
            "capacity_mm_true": 10.0,
            "k_per_day_true": 0.05,
            "s0_mm": 0.0,
            "error_fraction": 0.03,
            "error_seed": 11,
        },
        "calibration": {
            "model_name": "one_reservoir",
            "objective_metric": "kge",
            "global_method": method,
        },
        "bounds": {
            "C": [2.0, 20.0],
            "k": [0.01, 0.20],
        },
        "calibration_method": {
            "random_search": {
                "n_samples": 80,
                "seed": 42,
                "log_scale_indices": [],
            },
            "gp_mapping": {
                "seed": 42,
                "n_init": 16,
                "n_refine": 1,
                "batch_size": 6,
                "n_candidates": 100,
                "kappa": 2.5,
                "alpha": 1.0e-6,
                "jitter": 1.0e-8,
                "n_posterior_pool": 800,
                "n_posterior_samples": 120,
                "log_transform": True,
            },
        },
    }


def test_reservoir_workflow_random_search_smoke():
    """Reservoir workflow should run end-to-end and return structured results."""
    config = _reservoir_base_config(method="random_search")
    model_name = resolve_model_name(config)
    chronicle = build_noisy_reservoir_chronicle(config["chronicle"], model_name=model_name)
    calibration = calibrate_reservoir_model(chronicle, config, model_name=model_name)

    result = calibration["result"]
    assert isinstance(result, CalibrationResults)
    assert result.method == "random_search"
    assert result.samples is None
    assert result.params_best is not None
    assert {"NSE", "NSElog", "KGE", "r", "alpha", "beta"} <= set(calibration["metrics"])


def test_brutsaert_workflow_random_search_smoke():
    """Brutsaert workflow should run end-to-end with structured calibration outputs."""
    config = {
        "chronicle": {
            "Q0": 0.35,
            "K": 2.0e-4,
            "Sy": 0.28,
            "solution": "boussinesq",
            "A": 1.2e6,
            "ag": 0.7,
            "p": 0.346,
            "n_points": 35,
            "log_spacing": True,
            "t_min_days": 0.1,
            "error_fraction": 0.08,
            "random_seed": 123,
        },
        "calibration": {
            "objective_metric": "kge",
            "global_method": "random_search",
        },
        "bounds": {
            "K": [1.0e-5, 1.0e-3],
            "Sy": [0.20, 0.35],
        },
        "calibration_method": {
            "random_search": {
                "n_samples": 90,
                "seed": 7,
                "log_scale_indices": [0],
            }
        },
    }
    chronicle = build_noisy_coarse_sand_chronicle(config["chronicle"])
    calibration = calibrate_k_sy(chronicle, config)

    result = calibration["result_final"]
    assert isinstance(result, CalibrationResults)
    assert result.method == "random_search"
    assert result.samples is None
    assert result.params_best is not None
    assert {"NSE", "NSElog", "KGE", "r", "alpha", "beta"} <= set(calibration["metrics"])


def test_reservoir_workflow_gp_mapping_returns_samples():
    """Reservoir workflow should expose posterior samples for gp_mapping."""
    pytest.importorskip("sklearn")

    config = _reservoir_base_config(method="gp_mapping")
    model_name = resolve_model_name(config)
    chronicle = build_noisy_reservoir_chronicle(config["chronicle"], model_name=model_name)
    calibration = calibrate_reservoir_model(chronicle, config, model_name=model_name)

    result = calibration["result"]
    assert isinstance(result, CalibrationResults)
    assert result.method == "gp_mapping"
    assert result.samples is not None
    assert result.samples.shape[0] == 120
    assert result.samples.shape[1] == 2
