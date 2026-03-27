"""Objective-series transformations for calibration metrics."""

from __future__ import annotations

from typing import Callable

import numpy as np


def _as_float_array(values):
    """Convert input values to a NumPy float array."""
    return np.asarray(values, dtype=float)


def _validate_positive(value, *, name):
    out = float(value)
    if out <= 0.0:
        raise ValueError(f"{name} must be > 0")
    return out


class TransformationStrategy:
    """
    Registry of data transforms applicable before objective evaluation.

    Transform names are canonical, lowercase strings:
    - ``identity``
    - ``log``
    - ``sqrt``
    - ``inverse``
    - ``box_cox``
    """

    @staticmethod
    def identity(values):
        """Return values unchanged."""
        return _as_float_array(values)

    @staticmethod
    def log(values, *, epsilon=1.0e-6):
        """
        Apply ``log10(values + epsilon)``.

        ``epsilon`` must be strictly positive.
        """
        eps = _validate_positive(epsilon, name="epsilon")
        arr = _as_float_array(values)
        if np.any(arr + eps <= 0.0):
            raise ValueError("log transformation requires values + epsilon > 0")
        return np.log10(arr + eps)

    @staticmethod
    def sqrt(values):
        """Apply signed square-root transform."""
        arr = _as_float_array(values)
        return np.sqrt(np.abs(arr)) * np.sign(arr)

    @staticmethod
    def inverse(values, *, epsilon=1.0e-6):
        """
        Apply ``1 / (values + epsilon)``.

        ``epsilon`` must be strictly positive.
        """
        eps = _validate_positive(epsilon, name="epsilon")
        arr = _as_float_array(values)
        return 1.0 / (arr + eps)

    @staticmethod
    def box_cox(values, *, lambda_param=0.5):
        """
        Apply Box-Cox transform.

        Requires strictly positive values.
        """
        lam = float(lambda_param)
        arr = _as_float_array(values)
        if np.any(arr <= 0.0):
            raise ValueError("box_cox transformation requires strictly positive values")
        if abs(lam) < 1.0e-12:
            return np.log(arr)
        return (np.power(arr, lam) - 1.0) / lam

    _TRANSFORMATIONS: dict[str, Callable[..., np.ndarray]] = {
        "identity": identity,
        "log": log,
        "sqrt": sqrt,
        "inverse": inverse,
        "box_cox": box_cox,
    }

    @classmethod
    def get_transformation(cls, name: str):
        """Return a transformation callable from its canonical name."""
        key = normalize_transform_name(name)
        return cls._TRANSFORMATIONS[key]

    @classmethod
    def available_names(cls):
        """Return supported canonical transformation names."""
        return tuple(sorted(cls._TRANSFORMATIONS.keys()))


def normalize_transform_name(name: str | None):
    """Normalize and validate an objective transform name."""
    key = "identity" if name is None else str(name).strip().lower()
    if not key:
        key = "identity"
    if key not in TransformationStrategy._TRANSFORMATIONS:
        supported = ", ".join(TransformationStrategy.available_names())
        raise ValueError(
            f"Unsupported objective transform '{name}'. "
            f"Supported transforms: {supported}"
        )
    return key


def apply_transformation(values, *, transform="identity", params=None):
    """Apply one named transformation to an array-like input."""
    key = normalize_transform_name(transform)
    transform_fn = TransformationStrategy.get_transformation(key)
    kwargs = {} if params is None else dict(params)
    return transform_fn(values, **kwargs)


__all__ = (
    "TransformationStrategy",
    "apply_transformation",
    "normalize_transform_name",
)

