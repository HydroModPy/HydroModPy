"""Generic calibration class + baseflow-specific simulator helper."""

from dataclasses import dataclass

import numpy as np

from baseflow import simulate_baseflow
from calibration_method import DEFAULT_CALIBRATION_METHOD
from objective_fucntion import ObjectiveFunction


def _as_1d_array(values, name):
    """
    Convert an input sequence to a non-empty 1D float array.

    This utility centralizes shape/type normalization so all downstream
    computations can assume a consistent vector representation.
    """
    arr = np.asarray(values, dtype=float).ravel()
    if arr.size == 0:
        raise ValueError(f"{name} cannot be empty")
    return arr


@dataclass
class BaseflowConfig:
    """
    Fixed baseflow model settings used by the simulator adapter.

    Attributes
    ----------
    Q0 : float
        Initial discharge [m^3/s].
    solution : str
        Analytical recession form (`"boussinesq"` or `"exponential"`).
    b : float or None
        Aquifer thickness [m], required for exponential solution.
    A : float or None
        Watershed area [m^2].
    L : float or None
        Characteristic channel length [m].
    ag : float
        Active drainage fraction [-].
    p : float
        Linearization constant [-].
    """

    Q0: float
    solution: str = "boussinesq"
    b: float | None = None
    A: float | None = None
    L: float | None = None
    ag: float = 0.7
    p: float = 0.346


def make_baseflow_simulator(t_seconds, model_config: BaseflowConfig):
    """
    Build a simulator callable for the generic calibration class.

    The returned callable expects a parameter dictionary containing at least:
    - "K"
    - "Sy"

    Notes
    -----
    This adapter freezes all non-calibrated model settings (Q0, geometry,
    coefficients) and only exposes calibrated parameters through `params`.
    """
    t_seconds = _as_1d_array(t_seconds, "t_seconds")

    def _simulate(params):
        # Explicit conversion keeps behavior robust if params contains numpy scalars.
        k_val = float(params["K"])
        sy_val = float(params["Sy"])
        return simulate_baseflow(
            t=t_seconds,
            Q0=model_config.Q0,
            K=k_val,
            Sy=sy_val,
            solution=model_config.solution,
            b=model_config.b,
            A=model_config.A,
            L=model_config.L,
            ag=model_config.ag,
            p=model_config.p,
        )

    return _simulate


class Calibration:
    """
    Generic calibration class with objective metric and calibration-method switch.

    Parameters
    ----------
    observed : array-like
        Observed series used as calibration target.
    simulator : callable
        Callable receiving a parameter dictionary and returning a simulated
        series with same shape as `observed`.
    bounds : dict or sequence[(low, high)]
        Parameter bounds.
        If dict is provided, keys define parameter names.
    objective_metric : str
        Objective metric for score: "nse", "nse_log", or "kge" (aliases allowed).
    parameter_names : list[str] or None
        Optional explicit parameter order when bounds is not a dict.
    calibration_method : object or None
        Calibration-method registry exposing `calibrate(...)`.
        If None, the default registry from `calibration_method` is used.

    Design
    ------
    The class is intentionally model-agnostic:
    - `simulator` maps parameter dictionaries to simulated series.
    - this class handles metric evaluation and calibration orchestration.
    - parameter naming/order are managed internally for stable vectorization.
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
        # Normalize once at construction so all later computations share the same
        # array convention and shape checks.
        self.observed = _as_1d_array(observed, "observed")
        self.simulator = simulator
        self.objective = ObjectiveFunction(metric=objective_metric)
        self.parameter_names, self.bounds = self._normalize_bounds(bounds, parameter_names)
        if calibration_method is None:
            calibration_method = DEFAULT_CALIBRATION_METHOD
        # Any registry implementing calibrate(...) can be injected here.
        if not hasattr(calibration_method, "calibrate") or not callable(calibration_method.calibrate):
            raise TypeError(
                "calibration_method must expose a callable calibrate(...) method"
            )
        self.calibration_method = calibration_method
        # Keep latest run for debugging/reproducibility in interactive workflows.
        self.last_result = None

    @staticmethod
    def _normalize_bounds(bounds, parameter_names):
        """
        Normalize bounds and resolve parameter names/order.

        Accepted inputs:
        - dict: {"param": (low, high), ...}
        - sequence: [(low, high), ...] optionally with `parameter_names`

        Returns
        -------
        tuple[list[str], tuple[(float, float), ...]]
            Stable parameter order and validated bounds.
        """
        if isinstance(bounds, dict):
            # Dict mode preserves explicit semantic names (K, Sy, ...).
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

        # Sequence mode supports generic calibration problems where only vector
        # bounds are provided.
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

        This method is the single conversion gate used by calibration methods,
        so parameter order remains consistent across all evaluations.
        """
        if isinstance(params, dict):
            return np.array([float(params[name]) for name in self.parameter_names], dtype=float)

        vec = _as_1d_array(params, "params")
        if vec.size != len(self.parameter_names):
            raise ValueError(
                f"Expected {len(self.parameter_names)} parameters, got {vec.size}"
            )
        return vec

    def vector_to_params(self, vector):
        """
        Convert ordered parameter vector into a named parameter dictionary.

        Useful when model code expects semantic names (e.g. `K`, `Sy`)
        instead of raw calibration vectors.
        """
        vec = self.params_to_vector(vector)
        return {name: float(vec[i]) for i, name in enumerate(self.parameter_names)}

    def _in_bounds(self, vector):
        """
        Check whether a parameter vector lies inside calibration bounds.

        Bounds are inclusive on both sides.
        """
        vec = self.params_to_vector(vector)
        for i, (low, high) in enumerate(self.bounds):
            if not (low <= vec[i] <= high):
                return False
        return True

    def simulate(self, params):
        """
        Run simulator for one parameter set and validate output shape.

        Raises
        ------
        ValueError
            If simulator output shape is incompatible with observations.
        """
        p_dict = self.vector_to_params(params)
        simulated = _as_1d_array(self.simulator(p_dict), "simulated")
        if simulated.shape != self.observed.shape:
            raise ValueError("simulated series shape must match observed shape")
        return simulated

    def score(self, params, metric=None):
        """
        Compute score to maximize for parameter set.

        If `metric` is None, the default objective metric of the class is used.
        Typical score range is around (-inf, 1], with 1 meaning perfect fit.
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

        Out-of-bounds parameter vectors return +inf so generic calibration methods
        can safely explore unconstrained proposals without extra wrappers.
        """
        vec = self.params_to_vector(params)
        if not self._in_bounds(vec):
            return np.inf
        score = self.score(vec, metric=metric)
        return 1.0 - score

    def evaluate_all_metrics(self, params):
        """
        Evaluate all implemented hydrological metrics for one parameter set.

        This is mainly intended for post-calibration diagnostics and reporting.
        """
        sim = self.simulate(params)
        return self.objective.evaluate_all(self.observed, sim)

    def calibrate(self, method="random_search", **kwargs):
        """
        Calibrate parameters using the configured calibration-method registry.

        Notes
        -----
        Method-specific keyword arguments are forwarded to the selected
        calibration implementation through the method registry.

        Returns
        -------
        dict
            Calibration result dictionary enriched with:
            - `params_best`: named best parameters
            - `score_best`: objective score equivalent of `cost_best`
        """
        # Delegate method selection to the registry to keep this class focused
        # on calibration logic instead of method-registry details.
        result = self.calibration_method.calibrate(
            objective_cost=self.cost,
            bounds=self.bounds,
            method=method,
            **kwargs,
        )

        # Add user-friendly fields on top of generic method outputs.
        result["params_best"] = self.vector_to_params(result["x_best"])
        result["score_best"] = 1.0 - float(result["cost_best"])
        self.last_result = result
        return result
