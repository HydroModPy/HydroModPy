"""
Shared workflow helpers for the transient 1D groundwater calibration case.
"""

from __future__ import annotations

import numpy as np

from hydromodpy.calibration.analysis.diagnostics import compute_performance_metrics
from hydromodpy.calibration.core.engine import CalibrationEngine
from hydromodpy.calibration.core.engine_config import resolve_calibration_settings
from hydromodpy.calibration.cases.groundwater_1d.case_config import (
    validate_groundwater_1d_chronicle_config,
)
from hydromodpy.calibration.cases.groundwater_1d.model import (
    MODEL_PARAMETER_ORDER,
    Hydro1DNumerics,
    Hydro1DParameters,
    simulate,
)
from hydromodpy.calibration.cases.groundwater_1d.synthetic_data import (
    build_synthetic_groundwater_chronicle,
)


def build_noisy_groundwater_chronicle(chronicle_cfg):
    """
    Validate chronicle settings and generate synthetic observations.
    """
    config = validate_groundwater_1d_chronicle_config(chronicle_cfg)
    return build_synthetic_groundwater_chronicle(config)


def _build_parameter_object_from_candidate(chronicle, params):
    """
    Build full physical parameter object from calibrated vector + fixed context.
    """
    fixed = dict(chronicle["fixed_model_parameters"])
    params_dict = {str(k): float(v) for k, v in params.items()}
    missing = [name for name in MODEL_PARAMETER_ORDER if name not in params_dict]
    if missing:
        raise ValueError(f"Missing groundwater parameter(s): {missing}")

    return Hydro1DParameters(
        L=float(fixed["L"]),
        xi=float(params_dict["xi"]),
        Kam=float(params_dict["Kam"]),
        Kav=float(params_dict["Kav"]),
        Syam=float(params_dict["Syam"]),
        Syav=float(params_dict["Syav"]),
        H=float(fixed["H"]),
    )


def _build_numerics_object(chronicle):
    fixed = dict(chronicle["fixed_model_parameters"])
    return Hydro1DNumerics(
        nx=int(fixed["nx"]),
        formulation=str(fixed["formulation"]),
        max_picard_iterations=int(fixed["max_picard_iterations"]),
        picard_tolerance=float(fixed["picard_tolerance"]),
        picard_relaxation=float(fixed["picard_relaxation"]),
        head_floor=float(fixed["head_floor"]),
    )


def _extract_observation_vector_from_simulation(simulation, chronicle):
    h = np.asarray(simulation["h"], dtype=float)
    time_idx = np.asarray(chronicle["obs_time_indices"], dtype=int)
    node_idx = np.asarray(chronicle["obs_node_indices"], dtype=int)
    obs_matrix = h[np.ix_(time_idx, node_idx)]
    return obs_matrix.ravel(order="C")


def run_simulation_for_params(chronicle, params):
    """
    Run full h(x,t) simulation for one parameter mapping.
    """
    parameter_obj = _build_parameter_object_from_candidate(chronicle, params)
    numerics = _build_numerics_object(chronicle)
    return simulate(
        t=np.asarray(chronicle["t"], dtype=float),
        h0=np.asarray(chronicle["h0_series"], dtype=float),
        recharge=np.asarray(chronicle["recharge_series"], dtype=float),
        parameters=parameter_obj,
        numerics=numerics,
        h_init=chronicle["fixed_model_parameters"].get("h_init"),
        return_flux=True,
    )


def make_groundwater_simulator(chronicle):
    """
    Build simulator callable compatible with `CalibrationEngine`.

    Returns
    -------
    callable
        `simulate(params_dict) -> flattened observation vector`.
    """
    def _simulate(params):
        simulation = run_simulation_for_params(chronicle, params)
        return _extract_observation_vector_from_simulation(simulation, chronicle)

    return _simulate


def evaluate_metrics(observed, simulated):
    """
    Evaluate standard metrics on the flattened observation vector.
    """
    return compute_performance_metrics(
        observed=np.asarray(observed, dtype=float),
        simulated=np.asarray(simulated, dtype=float),
        nse_log_floor=1.0e-8,
    )


def calibrate_groundwater_model(chronicle, config):
    """
    Calibrate groundwater parameters and return a structured payload.
    """
    settings = resolve_calibration_settings(
        config,
        model_parameter_order=MODEL_PARAMETER_ORDER,
    )
    objective_metric = settings["objective_metric"]
    method = settings["method"]
    parameter_set = settings["parameter_set"]
    bounds = settings["bounds"]
    parameter_names = parameter_set.names

    simulator = make_groundwater_simulator(chronicle)
    calibration_obj = CalibrationEngine(
        observed=np.asarray(chronicle["obs_vector"], dtype=float),
        simulator=simulator,
        parameter_set=parameter_set,
        objective_metric=objective_metric,
    )

    result = calibration_obj.calibrate(
        method=method,
        **settings["method_kwargs"],
    )

    params_best = dict(result.params_best)
    params_true_all = dict(chronicle["true_params"])
    params_true = {name: float(params_true_all[name]) for name in parameter_names}

    obs_sim_best_vector = calibration_obj.simulate(result.x_best)
    metrics = evaluate_metrics(
        observed=chronicle["obs_vector"],
        simulated=obs_sim_best_vector,
    )
    simulation_best = run_simulation_for_params(chronicle, params_best)

    return {
        "calibration_obj": calibration_obj,
        "result": result,
        "params_best": params_best,
        "params_true": params_true,
        "parameter_names": parameter_names,
        "obs_sim_best_vector": obs_sim_best_vector,
        "simulation_best": simulation_best,
        "metrics": metrics,
        "objective_metric": objective_metric,
        "method": method,
        "bounds": bounds,
        "parameter_set": parameter_set,
    }


__all__ = (
    "MODEL_PARAMETER_ORDER",
    "build_noisy_groundwater_chronicle",
    "make_groundwater_simulator",
    "run_simulation_for_params",
    "evaluate_metrics",
    "calibrate_groundwater_model",
)


