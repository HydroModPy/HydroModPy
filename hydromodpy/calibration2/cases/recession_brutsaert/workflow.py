"""Shared calibration workflow helpers for the Brutsaert recession case."""

from __future__ import annotations

from dataclasses import dataclass

from hydromodpy.calibration2.analysis.diagnostics import compute_performance_metrics
from hydromodpy.calibration2.core.engine import CalibrationEngine, as_1d_array
from hydromodpy.calibration2.core.engine_config import resolve_calibration_settings
from hydromodpy.calibration2.cases.recession_brutsaert.case_config import (
    validate_brutsaert_chronicle_config,
)
from hydromodpy.calibration2.cases.recession_brutsaert.model import (
    generate_noisy_baseflow_profile,
    simulate_baseflow,
)


MODEL_PARAMETER_ORDER = ("K", "Sy")


@dataclass
class BaseflowConfig:
    """
    Fixed physical settings used by the simulator adapter.

    Only `K` and `Sy` are calibrated in this example; the remaining fields are
    treated as fixed context for one calibration run.
    """

    Q0: float
    solution: str = "boussinesq"
    b: float | None = None
    A: float | None = None
    L: float | None = None
    ag: float = 0.7
    p: float = 0.346


def build_noisy_coarse_sand_chronicle(profile_params):
    """
    Generate synthetic analytical + noisy chronicle.

    The output dictionary is the common data payload used by both calibration
    and plotting steps.
    """
    params = validate_brutsaert_chronicle_config(profile_params)
    if "error_fraction" in params:
        params["error_fraction"] = float(params["error_fraction"])
    if params.get("random_seed") is not None:
        params["random_seed"] = int(params["random_seed"])

    t_s, t_days, q_true, q_obs, tc_s, sigma = generate_noisy_baseflow_profile(**params)
    return {
        "params": params,
        "t_seconds": t_s,
        "t_days": t_days,
        "q_true": q_true,
        "q_obs": q_obs,
        "sigma": sigma,
        "tc_seconds": tc_s,
    }


def _true_baseflow_parameters(chronicle_params):
    """Return model parameters used to generate the synthetic truth."""
    return {
        "K": float(chronicle_params["K"]),
        "Sy": float(chronicle_params["Sy"]),
    }


def make_baseflow_simulator(t_seconds, model_config: BaseflowConfig):
    """
    Build a baseflow simulator callable compatible with generic `CalibrationEngine`.

    Parameters
    ----------
    t_seconds : array-like
        Time grid used for all model evaluations during one calibration run.
    model_config : BaseflowConfig
        Fixed physical context (everything except calibrated parameters).

    Returns
    -------
    callable
        Function `simulate(params_dict) -> simulated_series`.
    """
    t_seconds = as_1d_array(t_seconds, "t_seconds")

    def _simulate(params):
        params_all = {str(k): float(v) for k, v in params.items()}
        missing = [name for name in MODEL_PARAMETER_ORDER if name not in params_all]
        if missing:
            raise ValueError(f"Missing baseflow parameter(s): {missing}")

        return simulate_baseflow(
            t=t_seconds,
            Q0=model_config.Q0,
            K=float(params_all["K"]),
            Sy=float(params_all["Sy"]),
            solution=model_config.solution,
            b=model_config.b,
            A=model_config.A,
            L=model_config.L,
            ag=model_config.ag,
            p=model_config.p,
        )

    return _simulate


def calibrate_k_sy(chronicle, config):
    """
    Calibrate both Brutsaert parameters `K` and `Sy`.

    Returns
    -------
    dict
        Structured payload consumed by terminal summary and plotting.
    """
    params = chronicle["params"]
    settings = resolve_calibration_settings(
        config,
        model_parameter_order=MODEL_PARAMETER_ORDER,
    )
    objective_metric = settings["objective_metric"]
    global_method = settings["method"]
    parameter_set = settings["parameter_set"]
    bounds = settings["bounds"]
    parameter_names = parameter_set.names

    true_params_all = _true_baseflow_parameters(params)

    model_config = BaseflowConfig(
        Q0=float(params["Q0"]),
        solution=str(params["solution"]),
        b=params.get("b"),
        A=params.get("A"),
        L=params.get("L"),
        ag=float(params.get("ag", 0.7)),
        p=float(params.get("p", 0.346)),
    )

    simulator = make_baseflow_simulator(
        t_seconds=chronicle["t_seconds"],
        model_config=model_config,
    )
    calibration_obj = CalibrationEngine(
        observed=chronicle["q_obs"],
        simulator=simulator,
        parameter_set=parameter_set,
        objective_metric=objective_metric,
    )

    global_kwargs = settings["method_kwargs"]
    result_final = calibration_obj.calibrate(method=global_method, **global_kwargs)

    params_best = dict(result_final.params_best)
    params_true = {name: float(true_params_all[name]) for name in parameter_names}
    q_calib = calibration_obj.simulate(result_final.x_best)
    all_metrics = compute_performance_metrics(
        observed=calibration_obj.observed,
        simulated=q_calib,
        nse_log_floor=None,
    )

    return {
        "calibration_obj": calibration_obj,
        "bounds": bounds,
        "result_final": result_final,
        "params_best": params_best,
        "params_true": params_true,
        "parameter_names": parameter_names,
        "q_calib": q_calib,
        "metrics": all_metrics,
        "objective_metric": objective_metric,
        "global_method": global_method,
        "parameter_set": parameter_set,
    }


__all__ = (
    "MODEL_PARAMETER_ORDER",
    "BaseflowConfig",
    "build_noisy_coarse_sand_chronicle",
    "make_baseflow_simulator",
    "calibrate_k_sy",
)

