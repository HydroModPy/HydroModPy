"""Composable wrappers around calibration objective functions."""

from __future__ import annotations

from collections.abc import Mapping

from hydromodpy.calibration.core.objective_function import ObjectiveFunction
from hydromodpy.calibration.core.objective_transformations import (
    apply_transformation,
    normalize_transform_name,
)


class TransformedObjectiveFunction:
    """
    Wrap an `ObjectiveFunction` and transform observed/simulated data first.

    Notes
    -----
    The wrapper does not change metric semantics:
    - evaluation still delegates to the wrapped objective metric,
    - cost conversion still uses the wrapped metric direction.
    """

    def __init__(
        self,
        base_objective: ObjectiveFunction,
        *,
        transform="identity",
        transform_params=None,
    ):
        if not isinstance(base_objective, ObjectiveFunction):
            raise TypeError("base_objective must be an ObjectiveFunction instance")

        self.base_objective = base_objective
        self.transform = normalize_transform_name(transform)
        if transform_params is None:
            self.transform_params = {}
        elif isinstance(transform_params, Mapping):
            self.transform_params = dict(transform_params)
        else:
            raise TypeError("transform_params must be a mapping or None")

    @property
    def metric(self):
        """Metric name of the wrapped objective."""
        return self.base_objective.metric

    def evaluate(self, observed, simulated, metric=None, return_components=True):
        """Evaluate the wrapped objective after transforming both series."""
        obs_t = apply_transformation(
            observed,
            transform=self.transform,
            params=self.transform_params,
        )
        sim_t = apply_transformation(
            simulated,
            transform=self.transform,
            params=self.transform_params,
        )
        return self.base_objective.evaluate(
            observed=obs_t,
            simulated=sim_t,
            metric=metric,
            return_components=return_components,
        )

    def value_to_cost(self, value, metric=None):
        """Convert metric value to minimization cost."""
        return self.base_objective.value_to_cost(value, metric=metric)

    def evaluate_all(self, observed, simulated):
        """
        Evaluate canonical diagnostic metrics on transformed series.

        This mirrors `ObjectiveFunction.evaluate_all`.
        """
        obs_t = apply_transformation(
            observed,
            transform=self.transform,
            params=self.transform_params,
        )
        sim_t = apply_transformation(
            simulated,
            transform=self.transform,
            params=self.transform_params,
        )
        return self.base_objective.evaluate_all(obs_t, sim_t)


def build_objective(*, metric="nse", objective_options=None):
    """
    Build the runtime objective from metric + optional objective options.

    Parameters
    ----------
    metric : str
        Canonical metric name (`nse`, `nse_log`, `kge`, `rmse`).
    objective_options : Mapping | None
        Optional objective wrapper configuration, expected keys:
        - `transform` (str)
        - `transform_params` (mapping)
    """
    base = ObjectiveFunction(metric=metric)

    if objective_options is None:
        return base
    if not isinstance(objective_options, Mapping):
        raise TypeError("objective_options must be a mapping or None")

    options = dict(objective_options)
    transform = normalize_transform_name(options.get("transform", "identity"))
    raw_params = options.get("transform_params", {})
    if raw_params is None:
        transform_params = {}
    elif isinstance(raw_params, Mapping):
        transform_params = dict(raw_params)
    else:
        raise TypeError("objective_options['transform_params'] must be a mapping or None")

    if transform == "identity" and len(transform_params) == 0:
        return base

    return TransformedObjectiveFunction(
        base_objective=base,
        transform=transform,
        transform_params=transform_params,
    )


__all__ = (
    "TransformedObjectiveFunction",
    "build_objective",
)
