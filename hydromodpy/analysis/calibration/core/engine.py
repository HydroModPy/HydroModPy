"""Generic calibration engine for reference-case workflows."""

from __future__ import annotations

import time
from typing import Any
import numpy as np

from hydromodpy.analysis.calibration.core.parameters import CalibrationParameterSet
from hydromodpy.analysis.calibration.core.results import CalibrationResults
from hydromodpy.analysis.calibration.core.methods_dispatcher import DEFAULT_CALIBRATION_METHOD
from hydromodpy.analysis.calibration.core.objective_wrappers import build_objective


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
    observed : array-like | None
        Target time series (1D) for legacy single-series calibration.
    simulator : callable | None
        Forward model: `simulator(params_dict) -> simulated_series`.
        Output shape must match `observed` on the legacy path.
    bounds : dict or sequence of (low, high), optional
        Calibration bounds. Required when `parameter_set` is not provided.
    objective_metric : str, default="nse"
        Objective metric. Supported canonical values:
        `nse`, `nse_log`, `kge`, `rmse`, `mae`.
    objective_config : Mapping[str, Any] or None
        Optional objective wrapper settings (for example pre-metric series
        transformation). When omitted, no wrapper is applied.
        Ignored when `objective_evaluator` is provided.
    parameter_names : list[str] or None
        Explicit parameter order when `bounds` is a sequence.
    parameter_set : CalibrationParameterSet or compatible bounds definition, optional
        Canonical parameter-space definition. Mutually exclusive with `bounds`.
    objective_evaluator : object | None
        Optional composite evaluator exposing
        `evaluate(params_dict) -> evaluation(total_cost, total_score, ...)`.
        When provided, the historical `observed/simulator` single-series
        contract is bypassed in favor of this evaluator.
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
        objective_config=None,
        parameter_names=None,
        parameter_set=None,
        objective_evaluator=None,
        calibration_method=None,
    ):
        self.objective_evaluator = objective_evaluator
        if objective_evaluator is None:
            self.observed = as_1d_array(observed, "observed")
            if not callable(simulator):
                raise TypeError("simulator must be callable")
            self.simulator = simulator
            self.objective = build_objective(
                metric=objective_metric,
                objective_options=objective_config,
            )
        else:
            if not hasattr(objective_evaluator, "evaluate") or not callable(
                objective_evaluator.evaluate
            ):
                raise TypeError(
                    "objective_evaluator must expose a callable evaluate(...) method"
                )
            self.observed = None if observed is None else as_1d_array(observed, "observed")
            if simulator is not None and not callable(simulator):
                raise TypeError("simulator must be callable when provided")
            if simulator is None and hasattr(objective_evaluator, "simulate"):
                candidate = getattr(objective_evaluator, "simulate")
                simulator = candidate if callable(candidate) else None
            self.simulator = simulator
            self.objective = None
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
        self.last_evaluation = None

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
        Run simulator for one parameter set.

        On the legacy path, the output is validated as one 1D simulated series.
        On the composite path, the raw simulator payload is returned.
        """
        p_dict = self.vector_to_params(params)
        if self.objective_evaluator is not None:
            if self.simulator is None:
                raise RuntimeError(
                    "simulate() is unavailable because no simulator is attached to "
                    "the composite objective evaluator"
                )
            return self.simulator(p_dict)

        simulated = as_1d_array(self.simulator(p_dict), "simulated")
        if simulated.shape != self.observed.shape:
            raise ValueError("simulated series shape must match observed shape")
        return simulated

    @staticmethod
    def _serialize_objective_evaluation(evaluation: Any) -> dict[str, Any]:
        """Return one JSON-friendly view of an objective evaluation payload."""
        if hasattr(evaluation, "to_mapping") and callable(evaluation.to_mapping):
            return dict(evaluation.to_mapping())

        total_score = getattr(evaluation, "total_score", None)
        if total_score is None:
            total_score = -float(evaluation.total_cost)
        payload = {
            "total_cost": float(evaluation.total_cost),
            "total_score": float(total_score),
        }
        blocks = getattr(evaluation, "blocks", None)
        if blocks is not None:
            serialized_blocks = []
            for block in blocks:
                if hasattr(block, "to_mapping") and callable(block.to_mapping):
                    serialized_blocks.append(dict(block.to_mapping()))
                elif hasattr(block, "__dict__"):
                    serialized_blocks.append(dict(block.__dict__))
                else:
                    serialized_blocks.append({"value": repr(block)})
            payload["blocks"] = serialized_blocks
        return payload

    def _evaluate_composite(self, params):
        """Evaluate one composite objective payload from one parameter vector."""
        p_dict = self.vector_to_params(params)
        evaluation = self.objective_evaluator.evaluate(p_dict)
        if not hasattr(evaluation, "total_cost"):
            raise TypeError(
                "objective_evaluator.evaluate(...) must return an object exposing "
                "at least a total_cost attribute"
            )
        self.last_evaluation = evaluation
        return evaluation

    def score(self, params, metric=None):
        """
        Compute objective metric value for parameter set.
        """
        vec = self.params_to_vector(params)
        if self.objective_evaluator is not None:
            _ = metric
            evaluation = self._evaluate_composite(vec)
            total_score = getattr(evaluation, "total_score", None)
            if total_score is None:
                return float(-float(evaluation.total_cost))
            return float(total_score)

        sim = self.simulate(vec)
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
        For metrics where lower is better (`rmse`, `mae`):
            cost = metric_value
        """
        vec = self.params_to_vector(params)
        if not self._in_bounds(vec):
            return np.inf
        if self.objective_evaluator is not None:
            _ = metric
            evaluation = self._evaluate_composite(vec)
            return float(evaluation.total_cost)
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
        if self.objective_evaluator is not None:
            evaluation_best = self._evaluate_composite(result.x_best)
            score_best = getattr(evaluation_best, "total_score", None)
            if score_best is None:
                score_best = -float(evaluation_best.total_cost)
            result.metadata["objective_evaluation"] = self._serialize_objective_evaluation(
                evaluation_best
            )
        else:
            score_best = float(self.score(result.x_best))
        result.attach_context(
            vector_to_params=self.vector_to_params,
            score_best=score_best,
        )
        self.last_result = result
        return result

