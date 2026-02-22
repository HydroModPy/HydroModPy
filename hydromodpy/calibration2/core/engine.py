"""Generic calibration engine for reference-case workflows."""

from __future__ import annotations

import time
import numpy as np

from hydromodpy.calibration2.core.parameters import CalibrationParameterSet
from hydromodpy.calibration2.core.results import CalibrationResults
from hydromodpy.calibration2.core.methods_dispatcher import DEFAULT_CALIBRATION_METHOD
from hydromodpy.calibration2.core.objective_function import ObjectiveFunction


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

class CalibrationEngine:
    """
    Model-agnostic calibration engine.

    Parameters
    ----------
    observed : array-like
        Target time series (1D).
    simulator : callable
        Forward model: `simulator(params_dict) -> simulated_series`.
        Output shape must match `observed`.
    bounds : dict or sequence of (low, high), optional
        Calibration bounds. Required when `parameter_set` is not provided.
    objective_metric : str, default="nse"
        Objective metric. Supported canonical values:
        `nse`, `nse_log`, `kge`, `rmse`.
    parameter_names : list[str] or None
        Explicit parameter order when `bounds` is a sequence.
    parameter_set : CalibrationParameterSet or compatible bounds definition, optional
        Canonical parameter-space definition. Mutually exclusive with `bounds`.
    calibration_method : object or None
        Registry exposing `calibrate(objective_cost, bounds, method, **kwargs)`.
        If None, `DEFAULT_CALIBRATION_METHOD` is used.
    """

    def __init__(
        self,
        observed,
        simulator,
        bounds=None,
        objective_metric="nse",
        parameter_names=None,
        parameter_set=None,
        calibration_method=None,
    ):
        self.observed = as_1d_array(observed, "observed")
        self.simulator = simulator
        self.objective = ObjectiveFunction(metric=objective_metric)
        self.parameter_set = self._resolve_parameter_set(
            bounds=bounds,
            parameter_names=parameter_names,
            parameter_set=parameter_set,
        )

        if calibration_method is None:
            calibration_method = DEFAULT_CALIBRATION_METHOD
        if not hasattr(calibration_method, "calibrate") or not callable(calibration_method.calibrate):
            raise TypeError("calibration_method must expose a callable calibrate(...) method")
        self.calibration_method = calibration_method
        self.last_result = None

    @staticmethod
    def _resolve_parameter_set(bounds, parameter_names, parameter_set):
        """
        Resolve and validate calibration parameter definitions.
        """
        if parameter_set is not None:
            if bounds is not None:
                raise ValueError("Provide either bounds or parameter_set, not both")
            return CalibrationParameterSet.from_bounds(
                parameter_set,
                parameter_names=parameter_names,
            )
        if bounds is None:
            raise ValueError("bounds must be provided when parameter_set is not set")
        return CalibrationParameterSet.from_bounds(
            bounds,
            parameter_names=parameter_names,
        )

    def params_to_vector(self, params):
        """
        Convert params dict/vector into ordered 1D vector.
        """
        return self.parameter_set.vector_from(params)

    def vector_to_params(self, vector):
        """
        Convert ordered parameter vector into a named parameter dictionary.
        """
        return self.parameter_set.mapping_from(vector)

    def _in_bounds(self, vector):
        """
        Check whether a parameter vector lies inside calibration bounds.
        """
        return self.parameter_set.contains(vector)

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
        Compute objective metric value for parameter set.
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
        Compute minimization cost from the configured objective metric.

        For metrics where higher is better (`nse`, `nse_log`, `kge`):
            cost = 1 - metric_value
        For metrics where lower is better (`rmse`):
            cost = metric_value
        """
        vec = self.params_to_vector(params)
        if not self._in_bounds(vec):
            return np.inf
        value = self.score(vec, metric=metric)
        return float(self.objective.value_to_cost(value, metric=metric))

    def calibrate(self, method="simplex", **kwargs) -> CalibrationResults:
        """
        Calibrate parameters and return a `CalibrationResults` object.
        """
        t_start = time.perf_counter()
        raw_result = self.calibration_method.calibrate(
            objective_cost=self.cost,
            bounds=self.parameter_set.bounds,
            method=method,
            **kwargs,
        )
        calibration_time_seconds = float(time.perf_counter() - t_start)
        result = CalibrationResults.from_method_output(
            raw_result,
            default_method=method,
        )
        result.metadata["calibration_time_seconds"] = calibration_time_seconds
        score_best = float(self.score(result.x_best))
        result.attach_context(
            vector_to_params=self.vector_to_params,
            score_best=score_best,
        )
        self.last_result = result
        return result
