"""Generic calibration class for reference-case workflows."""

from __future__ import annotations

import numpy as np

from reference_cases.calibration_method import DEFAULT_CALIBRATION_METHOD
from reference_cases.objective_function import ObjectiveFunction


def as_1d_array(values, name):
    """
    Convert an input sequence to a validated 1D NumPy float array.

    Purpose
    -------
    This helper function standardizes user inputs before numerical processing.
    It ensures that the provided data:
        - can be converted to a NumPy array,
        - contains numeric (float) values,
        - is one-dimensional,
        - is not empty.

    Parameters
    ----------
    values : array-like
        Input data (list, tuple, NumPy array, pandas Series, etc.).
    name : str
        Name of the variable (used for informative error messages).

    Returns
    -------
    np.ndarray
        A 1D NumPy array of floats.

    Examples
    --------
    >>> as_1d_array([1, 2, 3], "x")
    array([1., 2., 3.])

    >>> as_1d_array([[1, 2, 3]], "x")
    array([1., 2., 3.])   # flattened to 1D

    >>> as_1d_array([], "x")
    ValueError: x cannot be empty

    Notes
    -----
    - `.ravel()` flattens multi-dimensional inputs into 1D.
    - `dtype=float` guarantees compatibility with numerical solvers.
    """

    # Convert input to a NumPy array of floats.
    # np.asarray:
    #   - Leaves NumPy arrays unchanged
    #   - Converts lists, tuples, pandas Series, etc.
    # dtype=float:
    #   - Ensures numerical consistency
    #   - Prevents unexpected integer division or type issues
    arr = np.asarray(values, dtype=float)

    # Flatten the array to 1D.
    # Example:
    #   [[1, 2, 3]]  →  [1, 2, 3]
    #   [[1], [2], [3]] → [1, 2, 3]
    arr = arr.ravel()

    # Validate non-empty input.
    # Prevents silent downstream failures (e.g., solver crashes,
    # invalid calibration, division by zero).
    if arr.size == 0:
        raise ValueError(f"{name} cannot be empty")

    return arr

class Calibration:
    """
    Generic parameter calibration engine for simulation models.

    This class links:
        - observed data (calibration target),
        - a user-defined simulator (forward model),
        - parameter bounds,
        - an objective metric,
        - and an optimization method.

    It provides a unified interface to:
        1) simulate model outputs for a parameter set,
        2) compute performance metrics,
        3) define a minimization cost,
        4) run an optimization procedure.

    Parameters
    ----------
    observed : array-like
        Target time series used for calibration.
        Must be numeric and 1D. Represents the reference signal
        the simulator should reproduce (e.g., observed discharge).

    simulator : callable
        Forward model with signature:
            simulator(params_dict) -> simulated_series
        where `params_dict` maps parameter names to numeric values.
        The returned series must have the same shape as `observed`.

    bounds : dict or sequence of (low, high)
        Defines the admissible parameter space.
        - If a dict is provided:
              {"C": (10, 500), "k": (0.01, 1.0)}
          keys define parameter names and order.
        - If a sequence is provided:
              [(10, 500), (0.01, 1.0)]
          parameter_names must be given (or default names p1, p2, ... are used).

        Each bound must satisfy: lower < upper.

    objective_metric : str, default="nse"
        Performance metric to maximize.
        Supported examples: "nse", "nse_log", "kge".
        Internally, optimization minimizes:
            cost = 1 - score

    parameter_names : list[str] or None
        Explicit parameter ordering when `bounds` is not a dict.
        Ensures consistent mapping between vectors and named parameters.

    calibration_method : object or None
        Optimization-method registry exposing:

            calibrate(objective_cost, bounds, method, **kwargs)

        If None, DEFAULT_CALIBRATION_METHOD is used.
        Allows plug-and-play integration of multiple search strategies
        (grid search, simplex, random search, Bayesian methods, etc.).

    Design philosophy
    -----------------
    - Model-agnostic: works with any simulator following the required interface.
    - Metric-agnostic: objective function handled via a dedicated evaluator.
    - Method-agnostic: optimization delegated to a registry.
    - Clear separation between model evaluation and optimization logic.
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
