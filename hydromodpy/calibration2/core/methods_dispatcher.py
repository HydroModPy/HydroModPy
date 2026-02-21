"""Calibration-method registry and default method dispatcher."""

from __future__ import annotations

from hydromodpy.calibration2.core.methods.da_mh_gp import delayed_acceptance_gp_mh_calibrate
from hydromodpy.calibration2.core.methods.gp_mapping import gp_mapping_calibrate
from hydromodpy.calibration2.core.methods.grid_search import grid_search_calibrate
from hydromodpy.calibration2.core.methods.nelder_mead import nelder_mead_calibrate
from hydromodpy.calibration2.core.methods.random_search import random_search_calibrate
from hydromodpy.calibration2.core.methods.simplex import simplex_calibrate
from hydromodpy.calibration2.core.methods_config import SUPPORTED_METHOD_NAMES


_DISPLAY_FAMILIES = (
    "global_search",
    "local_refinement",
    "bayesian_mcmc",
    "other",
)

_DISPLAY_LABELS = {
    "global_search": "Global search",
    "local_refinement": "Local refinement",
    "bayesian_mcmc": "Bayesian MCMC",
    "other": "Other",
}

_METHOD_DISPLAY_INFO = {
    "grid_search": (
        "global_search",
        "Exhaustive parameter-grid scan (deterministic, robust, expensive).",
    ),
    "random_search": (
        "global_search",
        "Random bounded sampling (stochastic global baseline).",
    ),
    "nelder_mead": (
        "local_refinement",
        "Nelder-Mead local simplex via scipy.optimize.minimize.",
    ),
    "simplex": (
        "local_refinement",
        "Classic simplex via scipy.optimize.fmin.",
    ),
    "gp_mapping": (
        "other",
        "GP surrogate posterior mapping with UCB refinement and importance resampling.",
    ),
    "da_mh_gp": (
        "bayesian_mcmc",
        "Delayed-acceptance Metropolis-Hastings with GP surrogate (RMSE objective).",
    ),
}

if tuple(sorted(_METHOD_DISPLAY_INFO)) != SUPPORTED_METHOD_NAMES:
    raise RuntimeError(
        "Built-in methods and method display info are inconsistent. "
        f"Expected {SUPPORTED_METHOD_NAMES}, got {tuple(sorted(_METHOD_DISPLAY_INFO))}."
    )


def _first_docline(func):
    """Return the first non-empty line of a callable docstring."""
    doc = getattr(func, "__doc__", None)
    if not doc:
        return "Custom calibration method."
    for raw in str(doc).splitlines():
        line = raw.strip()
        if line:
            return line
    return "Custom calibration method."


class CalibrationMethod:
    """Registry and dispatcher for calibration methods."""

    def __init__(self, methods=None):
        self._methods = {}
        if methods is not None:
            for name, calibrator in methods.items():
                self.register(name, calibrator)

    @staticmethod
    def _normalize_method_name(method):
        return str(method).strip().lower()

    def register(self, name, calibrator):
        key = self._normalize_method_name(name)
        if not key:
            raise ValueError("method name cannot be empty")
        if not callable(calibrator):
            raise TypeError("calibrator must be callable")
        self._methods[key] = calibrator
        return self

    def available_methods(self):
        return tuple(sorted(self._methods.keys()))

    def grouped_methods(self):
        grouped = {family: [] for family in _DISPLAY_FAMILIES}

        for name in self.available_methods():
            family, description = _METHOD_DISPLAY_INFO.get(name, ("other", None))
            if description is None:
                description = _first_docline(self._methods[name])
            grouped[family].append((name, description))

        for family in grouped:
            grouped[family] = tuple(grouped[family])
        return grouped

    def methods_overview(self):
        grouped = self.grouped_methods()
        lines = ["Available calibration methods:"]
        for family in _DISPLAY_FAMILIES:
            items = grouped.get(family, ())
            if not items:
                continue
            lines.append(f"- {_DISPLAY_LABELS.get(family, family)}")
            for method_name, description in items:
                lines.append(f"  * {method_name}: {description}")
        return "\n".join(lines)

    def calibrate(self, objective_cost, bounds, method="simplex", **kwargs):
        key = self._normalize_method_name(method)
        calibrator = self._methods.get(key)
        if calibrator is None:
            available = ", ".join(self.available_methods()) or "<none>"
            raise ValueError(f"Unknown method '{method}'. Supported: {available}")
        return calibrator(objective_cost=objective_cost, bounds=bounds, **kwargs)


DEFAULT_CALIBRATION_METHOD = CalibrationMethod(
    methods={
        "grid_search": grid_search_calibrate,
        "random_search": random_search_calibrate,
        "nelder_mead": nelder_mead_calibrate,
        "simplex": simplex_calibrate,
        "gp_mapping": gp_mapping_calibrate,
        "da_mh_gp": delayed_acceptance_gp_mh_calibrate,
    }
)


__all__ = (
    "CalibrationMethod",
    "DEFAULT_CALIBRATION_METHOD",
)
