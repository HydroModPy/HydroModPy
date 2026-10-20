"""Sampling helpers: where a search starts and how it draws, in each parameter's search space."""

from __future__ import annotations

import numpy as np

from hydromodpy.calibration.optim.parameters import CalibParameter, ParameterSpace


def search_space_center(space: ParameterSpace) -> np.ndarray:
    """Return one center point in search space, following each parameter's sampling."""
    return np.asarray([_center_parameter(param) for param in space.parameters], dtype=float)


def search_space_samples(
    space: ParameterSpace,
    rng: np.random.Generator,
    n_samples: int,
) -> np.ndarray:
    """Draw samples in search space, following each parameter's sampling."""
    n = max(0, int(n_samples))
    out = np.empty((n, space.dim), dtype=float)
    for index, param in enumerate(space.parameters):
        out[:, index] = _sample_parameter(param, rng, n)
    return out


def physical_sample(param: CalibParameter, rng: np.random.Generator) -> float:
    """Draw one sample in physical space, following the parameter's sampling."""
    y = float(_sample_parameter(param, rng, 1)[0])
    return param.to_physical(y)


def _center_parameter(param: CalibParameter) -> float:
    low = param.lower_transformed
    high = param.upper_transformed
    if param.sampling == "log_uniform":
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
    if param.sampling == "log_uniform":
        low_log = np.log10(float(param.lower))
        high_log = np.log10(float(param.upper))
        physical = 10.0 ** rng.uniform(low_log, high_log, size=n_samples)
        return np.asarray([param.to_transformed(float(value)) for value in physical], dtype=float)
    if param.sampling == "normal":
        sigma = max((high - low) / 6.0, 1e-12)
        return np.clip(rng.normal(0.5 * (low + high), sigma, size=n_samples), low, high)
    return rng.uniform(low, high, size=n_samples)
