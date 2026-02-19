"""Generic calibration class for reference-case workflows."""

from __future__ import annotations

import numpy as np

from reference_cases.calibration_method import DEFAULT_CALIBRATION_METHOD
from reference_cases.objective_function import ObjectiveFunction


def as_1d_array(values, name):
    """
    Convert an input sequence to a non-empty 1D float array.
    """
    arr = np.asarray(values, dtype=float).ravel()
    if arr.size == 0:
        raise ValueError(f"{name} cannot be empty")
    return arr


# Backward compatibility alias for older code.
_as_1d_array = as_1d_array


class Calibration:
    """
    Generic calibration class with objective metric and method registry.

    Parameters
    ----------
    observed : array-like
        Observed series used as calibration target.
    simulator : callable
        Callable receiving a named-parameter dictionary and returning a
        simulated series with same shape as `observed`.
    bounds : dict or sequence[(low, high)]
        Parameter bounds.
        If dict is provided, keys define parameter names/order.
    objective_metric : str
        Objective metric for score: "nse", "nse_log", or "kge" (aliases allowed).
    parameter_names : list[str] or None
        Optional explicit parameter order when bounds is not a dict.
    calibration_method : object or None
        Calibration-method registry exposing `calibrate(...)`.
        If None, uses `DEFAULT_CALIBRATION_METHOD`.
    """

    def __init__(
        self,
        observed,
        simulator,
        bounds,
        objective_metric="nse",
        parameter_names=None,
        calibration_method=None,
    ):
        self.observed = as_1d_array(observed, "observed")
        self.simulator = simulator
        self.objective = ObjectiveFunction(metric=objective_metric)
        self.parameter_names, self.bounds = self._normalize_bounds(bounds, parameter_names)

        if calibration_method is None:
            calibration_method = DEFAULT_CALIBRATION_METHOD
        if not hasattr(calibration_method, "calibrate") or not callable(calibration_method.calibrate):
            raise TypeError("calibration_method must expose a callable calibrate(...) method")
        self.calibration_method = calibration_method
        self.last_result = None

    @staticmethod
    def _normalize_bounds(bounds, parameter_names):
        """
        Normalize bounds and resolve parameter names/order.
        """
        if isinstance(bounds, dict):
            names = list(bounds.keys()) if parameter_names is None else list(parameter_names)
            norm_bounds = []
            for name in names:
                if name not in bounds:
                    raise ValueError(f"Missing bounds for parameter '{name}'")
                low, high = bounds[name]
                low = float(low)
                high = float(high)
                if low >= high:
                    raise ValueError(f"Invalid bounds for '{name}': lower must be < upper")
                norm_bounds.append((low, high))
            return names, tuple(norm_bounds)

        bounds_list = [(float(lo), float(hi)) for lo, hi in bounds]
        if any(lo >= hi for lo, hi in bounds_list):
            raise ValueError("Each bound must satisfy lower < upper")
        if parameter_names is None:
            names = [f"p{i + 1}" for i in range(len(bounds_list))]
        else:
            names = list(parameter_names)
            if len(names) != len(bounds_list):
                raise ValueError("parameter_names length must match number of bounds")
        return names, tuple(bounds_list)

    def params_to_vector(self, params):
        """
        Convert params dict/vector into ordered 1D vector.
        """
        if isinstance(params, dict):
            return np.array([float(params[name]) for name in self.parameter_names], dtype=float)

        vec = as_1d_array(params, "params")
        if vec.size != len(self.parameter_names):
            raise ValueError(f"Expected {len(self.parameter_names)} parameters, got {vec.size}")
        return vec

    def vector_to_params(self, vector):
        """
        Convert ordered parameter vector into a named parameter dictionary.
        """
        vec = self.params_to_vector(vector)
        return {name: float(vec[i]) for i, name in enumerate(self.parameter_names)}

    def _in_bounds(self, vector):
        """
        Check whether a parameter vector lies inside calibration bounds.
        """
        vec = self.params_to_vector(vector)
        for i, (low, high) in enumerate(self.bounds):
            if not (low <= vec[i] <= high):
                return False
        return True

    def simulate(self, params):
        """
        Run simulator for one parameter set and validate output shape.
        """
        p_dict = self.vector_to_params(params)
        simulated = as_1d_array(self.simulator(p_dict), "simulated")
        if simulated.shape != self.observed.shape:
            raise ValueError("simulated series shape must match observed shape")
        return simulated

    def score(self, params, metric=None):
        """
        Compute score to maximize for parameter set.
        """
        sim = self.simulate(params)
        eval_metric = self.objective.evaluate(
            observed=self.observed,
            simulated=sim,
            metric=metric,
            return_components=False,
        )
        return float(eval_metric["value"])

    def cost(self, params, metric=None):
        """
        Compute minimization cost = 1 - score.
        """
        vec = self.params_to_vector(params)
        if not self._in_bounds(vec):
            return np.inf
        score = self.score(vec, metric=metric)
        return 1.0 - score

    def evaluate_all_metrics(self, params):
        """
        Evaluate all implemented metrics for one parameter set.
        """
        sim = self.simulate(params)
        return self.objective.evaluate_all(self.observed, sim)

    def calibrate(self, method="simplex", **kwargs):
        """
        Calibrate parameters using the configured calibration-method registry.
        """
        method_key = str(method).strip().lower()
        if method_key in ("da_mh_gp", "delayed_acceptance_gp_mh"):
            # Provide default context required by Bayesian delayed-acceptance MH.
            kwargs.setdefault("observed", self.observed)
            kwargs.setdefault("simulator", self.simulator)
            kwargs.setdefault("parameter_names", tuple(self.parameter_names))
            kwargs.setdefault("vector_to_params", self.vector_to_params)

        result = self.calibration_method.calibrate(
            objective_cost=self.cost,
            bounds=self.bounds,
            method=method,
            **kwargs,
        )
        result["params_best"] = self.vector_to_params(result["x_best"])
        result["score_best"] = 1.0 - float(result["cost_best"])
        self.last_result = result
        return result
