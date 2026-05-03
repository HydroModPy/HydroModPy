"""Sampling helpers for calibration priors."""

from __future__ import annotations

import numpy as np

from hydromodpy.calibration.parameters import CalibParameter, ParameterSpace


def transformed_prior_center(space: ParameterSpace) -> np.ndarray:
    """Return one prior-aware center point in transformed space."""
    return np.asarray([_center_parameter(param) for param in space.parameters], dtype=float)


def transformed_prior_samples(
    space: ParameterSpace,
    rng: np.random.Generator,
    n_samples: int,
) -> np.ndarray:
    """Draw prior-aware samples in transformed space."""
    n = max(0, int(n_samples))
    out = np.empty((n, space.dim), dtype=float)
    for index, param in enumerate(space.parameters):
        out[:, index] = _sample_parameter(param, rng, n)
    return out


def physical_prior_sample(param: CalibParameter, rng: np.random.Generator) -> float:
    """Draw one prior-aware sample in physical space."""
    y = float(_sample_parameter(param, rng, 1)[0])
    return param.to_physical(y)


def _center_parameter(param: CalibParameter) -> float:
    low = param.lower_transformed
    high = param.upper_transformed
    if param.prior == "log_uniform":
        physical = float(np.sqrt(float(param.lower) * float(param.upper)))
        return param.to_transformed(physical)
    return 0.5 * (low + high)


def _sample_parameter(
    param: CalibParameter,
    rng: np.random.Generator,
    n_samples: int,
) -> np.ndarray:
    low = param.lower_transformed
    high = param.upper_transformed
    if n_samples == 0:
        return np.asarray([], dtype=float)
    if param.prior == "log_uniform":
        low_log = np.log10(float(param.lower))
        high_log = np.log10(float(param.upper))
        physical = 10.0 ** rng.uniform(low_log, high_log, size=n_samples)
        return np.asarray([param.to_transformed(float(value)) for value in physical], dtype=float)
    if param.prior == "normal":
        sigma = max((high - low) / 6.0, 1e-12)
        return np.clip(rng.normal(0.5 * (low + high), sigma, size=n_samples), low, high)
    return rng.uniform(low, high, size=n_samples)
