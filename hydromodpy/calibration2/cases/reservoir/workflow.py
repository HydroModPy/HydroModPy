# -*- coding: utf-8 -*-
"""
Shared calibration helpers for one/two reservoir reference workflows.

This module contains:
- model selection and metadata,
- simulator adapter creation,
- calibration execution and metrics.

Design intent
-------------
`run_calibration.py` stays short and orchestrates only the high-level flow.
This module centralizes reusable calibration logic so it can be called from:
- scripts,
- tests,
- future batch workflows.
"""

from __future__ import annotations

import numpy as np

from hydromodpy.calibration2.analysis.diagnostics import compute_performance_metrics
from hydromodpy.calibration2.core.engine_config import resolve_calibration_settings
from hydromodpy.calibration2.core.engine import CalibrationEngine
from hydromodpy.calibration2.cases.reservoir.forcing import make_piecewise_constant_daily_qin
from hydromodpy.calibration2.cases.reservoir.models.one_reservoir import (
    MODEL_DISPLAY_NAME as ONE_MODEL_DISPLAY_NAME,
    MODEL_NAME as ONE_MODEL_NAME,
    PARAMETER_ORDER as ONE_PARAMETER_ORDER,
    parse_chronicle_parameters as parse_one_chronicle_parameters,
    simulate_outflow as simulate_one_outflow,
)
from hydromodpy.calibration2.cases.reservoir.models.two_reservoirs import (
    MODEL_DISPLAY_NAME as TWO_MODEL_DISPLAY_NAME,
    MODEL_NAME as TWO_MODEL_NAME,
    PARAMETER_ORDER as TWO_PARAMETER_ORDER,
    parse_chronicle_parameters as parse_two_chronicle_parameters,
    simulate_outflow as simulate_two_outflow,
)

# Fallback used when `calibration.model_name` is not explicitly set in TOML.
DEFAULT_MODEL_NAME = ONE_MODEL_NAME

# Runtime dispatch table.
# Important distinction:
# - Pydantic validation (in `case_config.py` / `engine_config.py`) checks that
#   input values are valid.
# - `MODEL_REGISTRY` defines what the program *does* for each model:
#   which parameter order to use, which parser/simulator functions to call,
#   and which forcing convention/labels apply.
MODEL_REGISTRY = {
    ONE_MODEL_NAME: {
        # Human-readable label used in summaries/figures.
        "display_name": ONE_MODEL_DISPLAY_NAME,
        # Canonical parameter order used by calibration vectors.
        "parameter_order": ONE_PARAMETER_ORDER,
        # Model-specific extraction of true parameters and initial state.
        "parse_chronicle_parameters": parse_one_chronicle_parameters,
        # Model-specific forward simulator used by the generic engine.
        "simulate_outflow": simulate_one_outflow,
        # One-reservoir is forced by Qin(t) derived from effective rainfall.
        "forcing_kind": "qin",
        "forcing_label": "Qin [mm/day]",
    },
    TWO_MODEL_NAME: {
        "display_name": TWO_MODEL_DISPLAY_NAME,
        "parameter_order": TWO_PARAMETER_ORDER,
        "parse_chronicle_parameters": parse_two_chronicle_parameters,
        "simulate_outflow": simulate_two_outflow,
        # Two-reservoir variant is directly forced by precipitation P(t).
        "forcing_kind": "precip",
        "forcing_label": "P [mm/day]",
    },
}


def resolve_model_name(config):
    """
    Resolve model selector from TOML using strict canonical names.

    Enforcing canonical model names here avoids divergent naming rules between
    scripts and tests.
    """
    calibration_cfg = config.get("calibration", {})
    raw_value = str(calibration_cfg.get("model_name", DEFAULT_MODEL_NAME)).strip().lower()
    if raw_value not in MODEL_REGISTRY:
        allowed_txt = ", ".join(sorted(MODEL_REGISTRY))
        raise ValueError(
            f"Unknown model_name '{raw_value}'. Allowed canonical names: {allowed_txt}"
        )
    return raw_value


def get_model_display_name(model_name):
    """Return user-facing model label."""
    return MODEL_REGISTRY[model_name]["display_name"]


def get_model_parameter_order(model_name):
    """Return model parameter order expected by calibration routines."""
    return tuple(MODEL_REGISTRY[model_name]["parameter_order"])


def _true_model_parameters(cfg):
    """Return model parameters used to generate the synthetic truth."""
    return dict(cfg.true_params)


def make_reservoir_simulator(forcing_mm_day, initial_state, model_name):
    """
    Build simulator callable compatible with generic `CalibrationEngine`.

    Parameters
    ----------
    forcing_mm_day : array-like
        Daily forcing passed to the selected model (`Qin` or `P`).
    initial_state : dict
        Model initial state mapping.
    model_name : str
        Canonical model key in `MODEL_REGISTRY`.

    Returns
    -------
    callable
        Function `simulate(params_dict) -> qout_series`.
    """
    forcing = np.asarray(forcing_mm_day, dtype=float).ravel()
    if forcing.size == 0:
        raise ValueError("forcing_mm_day cannot be empty")

    t_eval = np.arange(forcing.size, dtype=float)
    # Adapter from discrete daily forcing to continuous-in-time callable.
    forcing_func = make_piecewise_constant_daily_qin(forcing)
    model_data = MODEL_REGISTRY[model_name]

    def _simulate(params):
        # Delegate to model-specific simulation implementation selected by registry.
        simulation = model_data["simulate_outflow"](
            params={str(k): float(v) for k, v in params.items()},
            initial_state=initial_state,
            forcing_func=forcing_func,
            t_span=(0.0, forcing.size - 1.0),
            t_eval=t_eval,
        )
        return np.asarray(simulation["qout"], dtype=float)

    return _simulate


def evaluate_metrics(observed, simulated, nse_log_floor=1e-8):
    """Evaluate NSE, NSElog and KGE."""
    return compute_performance_metrics(
        observed=observed,
        simulated=simulated,
        nse_log_floor=float(nse_log_floor),
    )


def calibrate_reservoir_model(chronicle, config, model_name):
    """
    Calibrate all model parameters defined for `model_name`.

    Returns
    -------
    dict
        Structured result payload consumed by plotting and terminal summaries.
    """
    # Resolve generic calibration settings with model-specific parameter order.
    model_parameter_order = get_model_parameter_order(model_name)
    settings = resolve_calibration_settings(
        config,
        model_parameter_order=model_parameter_order,
    )
    objective_metric = settings["objective_metric"]
    method = settings["method"]
    parameter_set = settings["parameter_set"]
    bounds = settings["bounds"]
    parameter_names = parameter_set.names

    # True parameters are used only for diagnostics (not for optimization).
    true_params_all = _true_model_parameters(chronicle["config"])
    simulator = make_reservoir_simulator(
        forcing_mm_day=chronicle["forcing_mm_day"],
        initial_state=chronicle["config"].initial_state,
        model_name=model_name,
    )
    calibration_obj = CalibrationEngine(
        observed=chronicle["q_obs_mm_day"],
        simulator=simulator,
        parameter_set=parameter_set,
        objective_metric=objective_metric,
    )

    calibrate_kwargs = settings["method_kwargs"]
    # Run chosen optimization/sampling method through the generic engine.
    result = calibration_obj.calibrate(method=method, **calibrate_kwargs)

    # Convert best result to named mapping and recompute fitted series.
    params_best = dict(result.params_best)
    params_true = {name: float(true_params_all[name]) for name in parameter_names}
    q_calib_mm_day = calibration_obj.simulate(result.x_best)

    # Always report a common metric set for cross-run comparison.
    metrics = evaluate_metrics(
        observed=chronicle["q_obs_mm_day"],
        simulated=q_calib_mm_day,
        nse_log_floor=1e-8,
    )

    return {
        "calibration_obj": calibration_obj,
        "result": result,
        "params_best": params_best,
        "params_true": params_true,
        "parameter_names": parameter_names,
        "q_calib_mm_day": q_calib_mm_day,
        "metrics": metrics,
        "objective_metric": objective_metric,
        "method": method,
        "bounds": bounds,
        "parameter_set": parameter_set,
        "model_name": model_name,
    }
