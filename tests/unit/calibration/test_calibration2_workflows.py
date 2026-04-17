"""Light integration tests for reference-case calibration workflows."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from hydromodpy.analysis.calibration.core.case_orchestrator import run_calibration_case
from hydromodpy.analysis.calibration.core.results import CalibrationResults
from hydromodpy.analysis.calibration.cases.recession_brutsaert.case_implementation import (
    CASE_IMPLEMENTATION as BRUTSAERT_CASE_IMPLEMENTATION,
)
from hydromodpy.analysis.calibration.cases.groundwater_1d.case_implementation import (
    CASE_IMPLEMENTATION as GROUNDWATER_CASE_IMPLEMENTATION,
)
from hydromodpy.analysis.calibration.cases.recession_brutsaert.workflow import (
    build_noisy_coarse_sand_chronicle,
    calibrate_k_sy,
)
from hydromodpy.analysis.calibration.cases.groundwater_1d.workflow import (
    build_noisy_groundwater_chronicle,
    calibrate_groundwater_model,
)
from hydromodpy.analysis.calibration.cases.reservoir.case_implementation import (
    CASE_IMPLEMENTATION as RESERVOIR_CASE_IMPLEMENTATION,
)
from hydromodpy.analysis.calibration.cases.reservoir.workflow import (
    calibrate_reservoir_model,
    resolve_model_name,
)
from hydromodpy.analysis.calibration.cases.reservoir.synthetic_data import build_noisy_reservoir_chronicle


GOLDEN_DIR = Path(__file__).resolve().parent / "golden"
BRUTSAERT_METHODS_GOLDEN_FILE = GOLDEN_DIR / "calibration2_brutsaert_methods_golden.json"
RESERVOIR_METHODS_GOLDEN_FILE = GOLDEN_DIR / "calibration_reservoir_methods_golden.json"


METHOD_ABS_TOL = {
    "grid_search": 1e-10,
    "random_search": 1e-10,
    "cma_es": 8e-3,
    "nelder_mead": 2e-4,
    "simplex": 2e-4,
    "gp_mapping": 3e-2,
    "da_mh_gp": 6e-2,
}


def _reservoir_base_config(*, method, model_name="one_reservoir"):
    chronicle = {
        "n_days": 40,
        "start_year": 2000,
        "target_annual_precip_mm": 400.0,
        "precip_seed": 7,
        "runoff_coeff": 0.20,
        "losses_mm_day": 0.8,
        "losses_months": [4, 5, 6, 7, 8, 9],
        "error_fraction": 0.03,
        "error_seed": 11,
        "solver_backend": "analytic",
    }
    if str(model_name) == "one_reservoir":
        chronicle.update(
            {
                "capacity_mm_true": 10.0,
                "k_per_day_true": 0.05,
                "s0_mm": 0.0,
            }
        )
        bounds = {
            "C": [2.0, 20.0],
            "k": [0.01, 0.20],
        }
    else:
        chronicle.update(
            {
                "a_true": 0.35,
                "kq_days_true": 3.0,
                "ks_days_true": 45.0,
                "sq0_mm": 0.0,
                "ss0_mm": 0.0,
            }
        )
        bounds = {
            "a": [0.05, 0.95],
            "Kq": [1.0, 10.0],
            "Ks": [15.0, 120.0],
        }
    return {
        "chronicle": chronicle,
        "calibration": {
            "model_name": model_name,
            "objective_metric": "kge",
            "global_method": method,
        },
        "bounds": bounds,
        "calibration_method": {
            "random_search": {
                "n_samples": 90,
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


def _brutsaert_base_config(*, method):
    return {
        "chronicle": {
            "Q0": 0.35,
            "K": 2.0e-4,
            "Sy": 0.28,
            "solution": "boussinesq",
            "A": 1.2e6,
            "ag": 0.7,
            "p": 0.346,
            "n_points": 24,
            "log_spacing": True,
            "t_min_days": 0.1,
            "error_fraction": 0.08,
            "random_seed": 123,
        },
        "calibration": {
            "objective_metric": "kge",
            "global_method": method,
        },
        "bounds": {
            "K": [1.0e-5, 1.0e-3],
            "Sy": [0.20, 0.35],
        },
        "calibration_method": {
            "grid_search": {
                "n_per_dim": 5,
                "log_scale_indices": [0],
            },
            "random_search": {
                "n_samples": 80,
                "seed": 7,
                "log_scale_indices": [0],
            },
            "cma_es": {
                "sigma0": 0.2,
                "max_evaluations": 36,
                "seed": 7,
                "normalize": True,
            },
            "nelder_mead": {
                "max_iter": 60,
            },
            "simplex": {
                "max_iter": 60,
                "max_fun": 120,
                "disp": False,
            },
            "gp_mapping": {
                "seed": 42,
                "n_init": 10,
                "n_refine": 1,
                "batch_size": 5,
                "n_candidates": 80,
                "kappa": 2.5,
                "alpha": 1.0e-6,
                "jitter": 1.0e-8,
                "n_posterior_pool": 600,
                "n_posterior_samples": 80,
                "log_transform": True,
            },
            "da_mh_gp": {
                "sigma_noise": 0.20,
                "n_init": 12,
                "n_samples": 80,
                "burn_in": 10,
                "thin": 2,
                "proposal_scale": 0.03,
                "retrain_interval": 10,
                "seed": 123,
            },
        },
    }


def _groundwater_base_config(*, method):
    return {
        "chronicle": {
            "n_days": 24,
            "dt_days": 1.0,
            "L_m": 200.0,
            "xi_true_m": 95.0,
            "nx": 31,
            "formulation_true": "linearized",
            "H_linearized_m": 9.0,
            "Kam_true_m_per_day": 3.0,
            "Kav_true_m_per_day": 1.1,
            "Syam_true": 0.16,
            "Syav_true": 0.09,
            "h0_m": 5.0,
            "recharge_mode": "hydro_step",
            "recharge_wet_m_per_day": 0.0018,
            "recharge_dry_m_per_day": 0.0004,
            "recharge_wet_months": [10, 11, 12, 1, 2, 3],
            "start_year": 2000,
            "target_annual_precip_mm": 600.0,
            "precip_seed": 17,
            "runoff_coeff": 0.15,
            "losses_mm_day": 1.2,
            "losses_months": [4, 5, 6, 7, 8, 9],
            "obs_x_m": [40.0, 95.0, 150.0, 190.0],
            "obs_t_stride": 2,
            "obs_noise_std_m": 0.01,
            "obs_seed": 77,
            "picard_max_iter": 25,
            "picard_tol": 1.0e-7,
            "picard_relaxation": 1.0,
            "head_floor_m": 1.0e-6,
        },
        "calibration": {
            "objective_metric": "rmse",
            "global_method": method,
        },
        "bounds": {
            "Kam": [1.0, 5.0],
            "Kav": [0.4, 2.5],
            "Syam": [0.08, 0.30],
            "Syav": [0.05, 0.20],
            "xi": [20.0, 180.0],
        },
        "calibration_method": {
            "random_search": {
                "n_samples": 48,
                "seed": 21,
                "log_scale_indices": [],
            },
        },
    }


def _to_serializable(value):
    if value is None:
        return None
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (np.floating, np.integer)):
        return float(value)
    if isinstance(value, (list, tuple)):
        return [_to_serializable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _to_serializable(v) for k, v in value.items()}
    return value


def _brutsaert_method_signature(calibration):
    result = calibration["result_final"]
    samples = result.samples
    signature = {
        "method": str(result.method),
        "x_best": _to_serializable(result.x_best),
        "cost_best": float(result.cost_best),
        "score_best": None if result.score_best is None else float(result.score_best),
        "n_evaluations": int(result.n_evaluations),
        "metrics": {
            "NSE": float(calibration["metrics"]["NSE"]),
            "NSElog": float(calibration["metrics"]["NSElog"]),
            "KGE": float(calibration["metrics"]["KGE"]),
            "r": float(calibration["metrics"]["r"]),
            "alpha": float(calibration["metrics"]["alpha"]),
            "beta": float(calibration["metrics"]["beta"]),
        },
    }
    if samples is not None:
        arr = np.asarray(samples, dtype=float)
        signature["samples"] = {
            "count": int(arr.shape[0]),
            "mean": _to_serializable(np.mean(arr, axis=0)),
            "std": _to_serializable(np.std(arr, axis=0)),
        }
    return signature


def _reservoir_method_signature(calibration):
    result = calibration["result"]
    samples = result.samples
    signature = {
        "model_name": str(calibration["model_name"]),
        "method": str(result.method),
        "x_best": _to_serializable(result.x_best),
        "cost_best": float(result.cost_best),
        "score_best": None if result.score_best is None else float(result.score_best),
        "n_evaluations": int(result.n_evaluations),
        "metrics": {
            "NSE": float(calibration["metrics"]["NSE"]),
            "NSElog": float(calibration["metrics"]["NSElog"]),
            "KGE": float(calibration["metrics"]["KGE"]),
            "r": float(calibration["metrics"]["r"]),
            "alpha": float(calibration["metrics"]["alpha"]),
            "beta": float(calibration["metrics"]["beta"]),
        },
    }
    if samples is not None:
        arr = np.asarray(samples, dtype=float)
        signature["samples"] = {
            "count": int(arr.shape[0]),
            "mean": _to_serializable(np.mean(arr, axis=0)),
            "std": _to_serializable(np.std(arr, axis=0)),
        }
    return signature


def _reservoir_golden_key(*, model_name, method):
    return f"{model_name}::{method}"


def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2)
        stream.write("\n")


def _load_json(path):
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def _assert_vectors_close(actual, expected, abs_tol):
    actual_arr = np.asarray(actual, dtype=float)
    expected_arr = np.asarray(expected, dtype=float)
    assert actual_arr.shape == expected_arr.shape
    assert np.allclose(actual_arr, expected_arr, atol=abs_tol, rtol=0.0)


def _assert_signature_close(actual, expected, abs_tol):
    assert actual["method"] == expected["method"]
    # Nelder-Mead (and similar optimisers) may converge in a slightly
    # different number of evaluations across platforms due to floating-point
    # rounding differences.  We tolerate a 5 % relative margin.
    n_actual = int(actual["n_evaluations"])
    n_expected = int(expected["n_evaluations"])
    assert n_actual == pytest.approx(n_expected, rel=0.05)
    _assert_vectors_close(actual["x_best"], expected["x_best"], abs_tol=abs_tol)
    assert float(actual["cost_best"]) == pytest.approx(float(expected["cost_best"]), abs=abs_tol, rel=0.0)

    if expected["score_best"] is None:
        assert actual["score_best"] is None
    else:
        assert float(actual["score_best"]) == pytest.approx(float(expected["score_best"]), abs=abs_tol, rel=0.0)

    for key in ("NSE", "NSElog", "KGE", "r", "alpha", "beta"):
        assert float(actual["metrics"][key]) == pytest.approx(
            float(expected["metrics"][key]),
            abs=abs_tol,
            rel=0.0,
        )

    actual_samples = actual.get("samples")
    expected_samples = expected.get("samples")
    if expected_samples is None:
        assert actual_samples is None
        return

    assert actual_samples is not None
    assert int(actual_samples["count"]) == int(expected_samples["count"])
    _assert_vectors_close(actual_samples["mean"], expected_samples["mean"], abs_tol=abs_tol)
    _assert_vectors_close(actual_samples["std"], expected_samples["std"], abs_tol=abs_tol)


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


def test_reservoir_case_orchestrator_random_search_smoke():
    """Reservoir case implementation should run through generic case orchestrator."""
    config = _reservoir_base_config(method="random_search")
    calibration = run_calibration_case(
        config_data=config,
        case_implementation=RESERVOIR_CASE_IMPLEMENTATION,
    )

    result = calibration["result"]
    assert isinstance(result, CalibrationResults)
    assert result.method == "random_search"
    assert result.samples is None
    assert result.params_best is not None
    assert calibration["model_name"] == "one_reservoir"
    assert calibration["chronicle"] is not None
    assert {"NSE", "NSElog", "KGE", "r", "alpha", "beta"} <= set(calibration["metrics"])


def test_brutsaert_workflow_random_search_smoke():
    """Brutsaert workflow should run end-to-end with structured calibration outputs."""
    config = _brutsaert_base_config(method="random_search")
    chronicle = build_noisy_coarse_sand_chronicle(config["chronicle"])
    calibration = calibrate_k_sy(chronicle, config)

    result = calibration["result_final"]
    assert isinstance(result, CalibrationResults)
    assert result.method == "random_search"
    assert result.samples is None
    assert result.params_best is not None
    assert {"NSE", "NSElog", "KGE", "r", "alpha", "beta"} <= set(calibration["metrics"])


def test_brutsaert_case_orchestrator_random_search_smoke():
    """Brutsaert case implementation should run through generic case orchestrator."""
    config = _brutsaert_base_config(method="random_search")
    calibration = run_calibration_case(
        config_data=config,
        case_implementation=BRUTSAERT_CASE_IMPLEMENTATION,
    )

    result = calibration["result"]
    assert isinstance(result, CalibrationResults)
    assert result.method == "random_search"
    assert result.samples is None
    assert result.params_best is not None
    assert calibration["chronicle"] is not None
    assert calibration["result_final"] is result
    assert {"NSE", "NSElog", "KGE", "r", "alpha", "beta"} <= set(calibration["metrics"])


def test_groundwater_workflow_random_search_smoke():
    """Groundwater workflow should run end-to-end with structured outputs."""
    config = _groundwater_base_config(method="random_search")
    chronicle = build_noisy_groundwater_chronicle(config["chronicle"])
    calibration = calibrate_groundwater_model(chronicle, config)

    result = calibration["result"]
    assert isinstance(result, CalibrationResults)
    assert result.method == "random_search"
    assert result.samples is None
    assert result.params_best is not None
    assert calibration["simulation_best"] is not None
    assert {"NSE", "NSElog", "KGE", "r", "alpha", "beta"} <= set(calibration["metrics"])


def test_groundwater_case_orchestrator_random_search_smoke():
    """Groundwater case should run through generic case orchestrator."""
    config = _groundwater_base_config(method="random_search")
    calibration = run_calibration_case(
        config_data=config,
        case_implementation=GROUNDWATER_CASE_IMPLEMENTATION,
    )

    result = calibration["result"]
    assert isinstance(result, CalibrationResults)
    assert result.method == "random_search"
    assert result.samples is None
    assert result.params_best is not None
    assert calibration["chronicle"] is not None
    assert calibration["result_final"] is result
    assert calibration["simulation_best"] is not None
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


@pytest.mark.parametrize(
    ("model_name", "method"),
    (
        ("one_reservoir", "random_search"),
        ("two_reservoir", "random_search"),
    ),
)
def test_reservoir_workflow_methods_golden(model_name, method, update_goldens):
    """Non-regression check for reservoir calibration methods using golden values."""
    config = _reservoir_base_config(method=method, model_name=model_name)
    resolved_model_name = resolve_model_name(config)
    chronicle = build_noisy_reservoir_chronicle(
        config["chronicle"],
        model_name=resolved_model_name,
    )
    calibration = calibrate_reservoir_model(
        chronicle,
        config,
        model_name=resolved_model_name,
    )
    actual = _reservoir_method_signature(calibration)
    key = _reservoir_golden_key(model_name=model_name, method=method)

    if update_goldens:
        payload = {}
        if RESERVOIR_METHODS_GOLDEN_FILE.exists():
            payload = _load_json(RESERVOIR_METHODS_GOLDEN_FILE)
        payload[key] = actual
        _write_json(RESERVOIR_METHODS_GOLDEN_FILE, payload)
        return

    if not RESERVOIR_METHODS_GOLDEN_FILE.exists():
        pytest.fail(
            f"Missing golden reference file: {RESERVOIR_METHODS_GOLDEN_FILE}. "
            "Run tests with --update-goldens to generate it."
        )

    expected_all = _load_json(RESERVOIR_METHODS_GOLDEN_FILE)
    assert key in expected_all, (
        f"Missing golden entry '{key}' in {RESERVOIR_METHODS_GOLDEN_FILE}. "
        "Run tests with --update-goldens to refresh."
    )
    expected = expected_all[key]
    assert actual.get("model_name") == expected.get("model_name")
    _assert_signature_close(actual, expected, abs_tol=METHOD_ABS_TOL[method])


@pytest.mark.parametrize(
    "method",
    ("grid_search", "random_search", "cma_es", "nelder_mead", "simplex", "gp_mapping", "da_mh_gp"),
)
def test_brutsaert_workflow_multiple_methods_smoke(method):
    """Brutsaert workflow should run with multiple calibration methods."""
    if method in ("nelder_mead", "simplex"):
        pytest.importorskip("scipy")
    if method == "cma_es":
        pytest.importorskip("cma")
    if method == "gp_mapping":
        pytest.importorskip("sklearn")

    config = _brutsaert_base_config(method=method)
    if method == "da_mh_gp":
        config["calibration"]["objective_metric"] = "rmse"

    chronicle = build_noisy_coarse_sand_chronicle(config["chronicle"])
    calibration = calibrate_k_sy(chronicle, config)

    result = calibration["result_final"]
    assert isinstance(result, CalibrationResults)
    assert result.method == method
    assert result.params_best is not None
    assert {"NSE", "NSElog", "KGE", "r", "alpha", "beta"} <= set(calibration["metrics"])


@pytest.mark.parametrize(
    "method",
    ("grid_search", "random_search", "cma_es", "nelder_mead", "simplex", "gp_mapping", "da_mh_gp"),
)
def test_brutsaert_workflow_methods_golden(method, update_goldens):
    """Non-regression check for Brutsaert calibration methods using golden values."""
    if method in ("nelder_mead", "simplex"):
        pytest.importorskip("scipy")
    if method == "cma_es":
        pytest.importorskip("cma")
    if method == "gp_mapping":
        pytest.importorskip("sklearn")

    config = _brutsaert_base_config(method=method)
    if method == "da_mh_gp":
        config["calibration"]["objective_metric"] = "rmse"

    chronicle = build_noisy_coarse_sand_chronicle(config["chronicle"])
    calibration = calibrate_k_sy(chronicle, config)
    actual = _brutsaert_method_signature(calibration)

    if update_goldens:
        payload = {}
        if BRUTSAERT_METHODS_GOLDEN_FILE.exists():
            payload = _load_json(BRUTSAERT_METHODS_GOLDEN_FILE)
        payload[str(method)] = actual
        _write_json(BRUTSAERT_METHODS_GOLDEN_FILE, payload)
        return

    if not BRUTSAERT_METHODS_GOLDEN_FILE.exists():
        pytest.fail(
            f"Missing golden reference file: {BRUTSAERT_METHODS_GOLDEN_FILE}. "
            "Run tests with --update-goldens to generate it."
        )

    expected_all = _load_json(BRUTSAERT_METHODS_GOLDEN_FILE)
    assert method in expected_all, (
        f"Missing golden entry for method '{method}' in {BRUTSAERT_METHODS_GOLDEN_FILE}. "
        "Run tests with --update-goldens to refresh."
    )
    expected = expected_all[method]
    _assert_signature_close(actual, expected, abs_tol=METHOD_ABS_TOL[method])

