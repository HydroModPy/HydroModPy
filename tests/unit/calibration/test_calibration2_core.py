"""Unit tests for refactored reference-case calibration core."""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.analysis.calibration.core.engine_config import (
    resolve_calibration_settings,
)
from hydromodpy.analysis.calibration.core.methods_config import (
    normalize_format_method_kwargs,
)
from hydromodpy.analysis.calibration.core.engine import CalibrationEngine
from hydromodpy.analysis.calibration.core.methods_dispatcher import CalibrationMethod
from hydromodpy.analysis.calibration.core.results import CalibrationResults
from hydromodpy.analysis.calibration.core.objective_function import ObjectiveFunction


def test_da_mh_forces_rmse_metric_with_warning():
    """DA-MH config should force RMSE objective metric with a warning."""
    config = {
        "chronicle": {},
        "calibration": {
            "objective_metric": "kge",
            "global_method": "da_mh_gp",
        },
        "bounds": {"a": [0.05, 0.95]},
        "calibration_method": {"da_mh_gp": {}},
    }

    with pytest.warns(UserWarning, match="objective_metric is forced to 'rmse'"):
        settings = resolve_calibration_settings(
            config,
            model_parameter_order=("a",),
        )
    assert settings["objective_metric"] == "rmse"


def test_resolve_calibration_settings_exposes_objective_options():
    """Objective section should be validated then propagated to runtime settings."""
    config = {
        "chronicle": {},
        "calibration": {
            "objective_metric": "rmse",
            "global_method": "random_search",
        },
        "objective": {
            "transform": "inverse",
            "transform_params": {"epsilon": 0.1},
        },
        "bounds": {"a": [0.05, 0.95]},
        "calibration_method": {"random_search": {"n_samples": 10, "seed": 1}},
    }

    settings = resolve_calibration_settings(
        config,
        model_parameter_order=("a",),
    )
    assert settings["objective"]["transform"] == "inverse"
    assert settings["objective"]["transform_params"] == {"epsilon": 0.1}


def test_unknown_method_kwargs_are_rejected():
    """Built-in methods reject unsupported TOML kwargs early."""
    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
        normalize_format_method_kwargs(
            method="da_mh_gp",
            method_kwargs={"foo": 1.0},
            parameter_names=("a", "Kq", "Ks"),
        )


def test_da_mh_named_mapping_is_reordered_by_parameter_names():
    """Per-parameter mappings are normalized in canonical parameter order."""
    normalized = normalize_format_method_kwargs(
        method="da_mh_gp",
        method_kwargs={"proposal_scale": {"Kq": 0.5, "a": 0.05, "Ks": 5.0}},
        parameter_names=("a", "Kq", "Ks"),
    )
    assert normalized["proposal_scale"] == [0.05, 0.5, 5.0]


def test_calibration_engine_da_mh_does_not_inject_legacy_context():
    """Engine dispatch should remain method-agnostic (no DA-MH-only kwargs)."""
    captured = {}

    def _fake_da_mh(objective_cost, bounds, **kwargs):
        captured.update(kwargs)
        x = np.array([0.5 * (lo + hi) for lo, hi in bounds], dtype=float)
        return CalibrationResults(
            method="da_mh_gp",
            x_best=x,
            params_best=None,
            cost_best=float(objective_cost(x)),
            score_best=None,
            n_evaluations=1,
        )

    methods = CalibrationMethod({"da_mh_gp": _fake_da_mh})

    def _simulator(params):
        return np.array([params["a"], params["a"]], dtype=float)

    engine = CalibrationEngine(
        observed=np.array([1.0, 2.0], dtype=float),
        simulator=_simulator,
        bounds={"a": (0.0, 5.0)},
        objective_metric="rmse",
        calibration_method=methods,
    )
    result = engine.calibrate(method="da_mh_gp")

    assert "observed" not in captured
    assert "simulator" not in captured
    assert "parameter_names" not in captured
    assert "vector_to_params" not in captured
    assert isinstance(result, CalibrationResults)
    assert np.isclose(result.score_best, result.cost_best)
    assert "calibration_time_seconds" in result.metadata
    assert float(result.metadata["calibration_time_seconds"]) >= 0.0


def test_objective_value_to_cost_respects_metric_direction():
    """Cost conversion must differ for maximize-vs-minimize metrics."""
    maximize_obj = ObjectiveFunction(metric="kge")
    minimize_obj = ObjectiveFunction(metric="rmse")

    assert np.isclose(maximize_obj.value_to_cost(0.8), 0.2)
    assert np.isclose(minimize_obj.value_to_cost(0.8), 0.8)


def test_calibration_engine_applies_objective_transformation_before_scoring():
    """Configured objective transform must be applied to observed/simulated series."""
    eps = 1.0e-12
    observed = np.array([1.0, 100.0], dtype=float)

    def _simulator(params):
        return np.array([float(params["a"]), float(params["a"])], dtype=float)

    engine = CalibrationEngine(
        observed=observed,
        simulator=_simulator,
        bounds={"a": (1.0, 100.0)},
        objective_metric="rmse",
        objective_config={"transform": "log", "transform_params": {"epsilon": eps}},
    )

    value = engine.score(np.array([10.0], dtype=float))
    expected = float(
        np.sqrt(
            np.mean(
                (
                    np.log10(np.array([10.0, 10.0], dtype=float) + eps)
                    - np.log10(observed + eps)
                )
                ** 2
            )
        )
    )
    assert value == pytest.approx(expected, abs=1.0e-12, rel=0.0)


def test_calibration_results_prefers_posterior_samples_and_keeps_chain():
    """Canonical results should expose posterior samples as distribution."""
    raw = {
        "method": "da_mh_gp",
        "x_best": np.array([0.3, 3.0], dtype=float),
        "cost_best": 0.1,
        "n_evaluations": 50,
        "samples": np.array([[0.1, 2.0], [0.2, 2.5], [0.3, 3.0]], dtype=float),
        "posterior_samples": np.array([[0.25, 2.8], [0.31, 3.1]], dtype=float),
        "stage1_accept_rate": 0.4,
    }

    result = CalibrationResults.from_method_output(
        raw,
        default_method="da_mh_gp",
    )
    result.attach_context(
        vector_to_params=lambda x: {"a": float(x[0]), "Kq": float(x[1])},
        score_best=0.9,
    )

    assert result.has_samples
    assert result.samples.shape == (2, 2)
    assert "chain_samples" in result.metadata
    assert result.metadata["chain_samples"].shape == (3, 2)
    assert result.params_best == {"a": 0.3, "Kq": 3.0}
    assert np.isclose(result.score_best, 0.9)

