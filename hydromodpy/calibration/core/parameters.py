"""
Parameter-space objects used by reference-case calibration workflows.

Why parameter order is indispensable
------------------------------------
Calibration algorithms optimize unnamed vectors, for example:
    x = [x0, x1, x2]
They do not know that x0 means "K" and x1 means "Sy".

Hydrological simulators, however, are written with named parameters:
    {"K": ..., "Sy": ...}

So the code must enforce one canonical parameter order everywhere.
Without that contract, values can be silently swapped.

Example:
- Canonical order: ("K", "Sy")
- Optimizer vector: [2e-4, 0.28]
- Correct mapping: {"K": 2e-4, "Sy": 0.28}

If another part of the code interprets the same vector as ("Sy", "K"),
you get:
    {"Sy": 2e-4, "K": 0.28}
This is a physically different model state and can completely corrupt
calibration results while still running without obvious errors.

This module centralizes that contract:
- validate parameter names and bounds,
- keep a deterministic order,
- convert dict <-> vector consistently,
- perform shared in-bounds checks and clipping.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Mapping

import numpy as np


@dataclass(frozen=True, slots=True)
class CalibrationParameter:
    """
    Immutable parameter definition with validated name and bounds.
    """

    name: str
    lower: float
    upper: float

    def __post_init__(self):
        name = str(self.name).strip()
        lower = float(self.lower)
        upper = float(self.upper)

        if not name:
            raise ValueError("parameter name cannot be empty")
        if not math.isfinite(lower) or not math.isfinite(upper):
            raise ValueError(f"Bounds for '{name}' must be finite values")
        if lower >= upper:
            raise ValueError(f"Invalid bounds for '{name}': lower must be < upper")

        object.__setattr__(self, "name", name)
        object.__setattr__(self, "lower", lower)
        object.__setattr__(self, "upper", upper)


class CalibrationParameterSet:
    """
    Ordered, validated collection of calibration parameters.

    This object centralizes:
    - parameter ordering,
    - bounds validation,
    - dict/vector conversion helpers,
    - in-bounds checks.
    """

    def __init__(self, parameters):
        parsed = []
        for item in parameters:
            if isinstance(item, CalibrationParameter):
                parsed.append(item)
                continue
            raise TypeError("parameters must contain CalibrationParameter instances")

        if not parsed:
            raise ValueError("CalibrationParameterSet cannot be empty")

        seen = set()
        duplicates = set()
        for param in parsed:
            if param.name in seen:
                duplicates.add(param.name)
            else:
                seen.add(param.name)
        duplicates = sorted(duplicates)
        if duplicates:
            dup_txt = ", ".join(duplicates)
            raise ValueError(f"Duplicate parameter name(s): {dup_txt}")

        self._parameters = tuple(parsed)
        self._names = tuple(p.name for p in self._parameters)
        self._lower = np.array([p.lower for p in self._parameters], dtype=float)
        self._upper = np.array([p.upper for p in self._parameters], dtype=float)

    @classmethod
    def from_bounds(cls, bounds, *, parameter_names=None):
        """
        Build a parameter set from bounds.

        Supported examples:
        - Example 1: dict input
          `{"alpha": (0.0, 1.0), "beta": (10.0, 20.0)}`
        - Example 2: dict input + explicit order
          `parameter_names=["beta", "alpha"]`
        - Example 3: sequence of tuples
          `[(0.0, 1.0), (10.0, 20.0)]` -> auto names `p1`, `p2`
        - Example 4: sequence of tuples + explicit names
        - Example 5: sequence of `CalibrationParameter`
        - Example 6: existing `CalibrationParameterSet`
        """
        # Case 1 (Example 6):
        # Input is already a CalibrationParameterSet.
        # Return as-is, with optional order validation.
        if isinstance(bounds, cls):
            if parameter_names is None:
                return bounds
            expected = tuple(str(name) for name in parameter_names)
            if bounds.names != expected:
                raise ValueError(
                    "parameter_names order is inconsistent with provided parameter set"
                )
            return bounds

        # Case 2 (Example 5):
        # Input is a sequence of CalibrationParameter objects.
        # Build directly from provided parameter objects.
        if not isinstance(bounds, Mapping):
            raw_items = list(bounds)
            if raw_items and all(
                isinstance(item, CalibrationParameter) for item in raw_items
            ):
                candidate = cls(raw_items)
                if parameter_names is not None:
                    expected = tuple(str(name) for name in parameter_names)
                    if candidate.names != expected:
                        raise ValueError(
                            "parameter_names order is inconsistent with provided parameters"
                        )
                return candidate
        else:
            raw_items = None

        # Case 3 (Examples 1-2):
        # Input is a dictionary {name: (low, high)}.
        # Use dict order unless an explicit parameter_names order is provided.
        if isinstance(bounds, Mapping):
            if parameter_names is None:
                names = [str(name) for name in bounds.keys()]
            else:
                names = [str(name) for name in parameter_names]
            params = []
            for name in names:
                if name not in bounds:
                    raise ValueError(f"Missing bounds for parameter '{name}'")
                low, high = bounds[name]
                params.append(CalibrationParameter(name=name, lower=low, upper=high))
            return cls(params)

        # Case 4 (Examples 3-4):
        # Input is a plain sequence of (low, high) pairs.
        # Auto-name parameters (p1, p2, ...) when names are not provided.
        bounds_iterable = raw_items if raw_items is not None else list(bounds)
        bounds_list = [(float(lo), float(hi)) for lo, hi in bounds_iterable]
        if parameter_names is None:
            names = [f"p{i + 1}" for i in range(len(bounds_list))]
        else:
            names = [str(name) for name in parameter_names]
            if len(names) != len(bounds_list):
                raise ValueError("parameter_names length must match number of bounds")

        params = [
            CalibrationParameter(name=name, lower=low, upper=high)
            for name, (low, high) in zip(names, bounds_list)
        ]
        return cls(params)

    @property
    def names(self):
        """Ordered tuple of parameter names."""
        return self._names

    @property
    def bounds(self):
        """Ordered tuple of `(lower, upper)` bounds."""
        return tuple((p.lower, p.upper) for p in self._parameters)

    @property
    def dimension(self):
        """Number of calibration parameters."""
        return len(self._parameters)

    @property
    def lower_bounds(self):
        """Lower-bound vector in parameter order."""
        return self._lower.copy()

    @property
    def upper_bounds(self):
        """Upper-bound vector in parameter order."""
        return self._upper.copy()

    def as_bounds_dict(self):
        """Return `{name: (lower, upper)}` in stored order."""
        return {p.name: (p.lower, p.upper) for p in self._parameters}

    def vector_from(self, values):
        """
        Convert mapping/vector values to a float vector in parameter order.
        """
        if isinstance(values, Mapping):
            missing = [name for name in self._names if name not in values]
            if missing:
                raise ValueError(f"Missing parameter value(s): {missing}")
            return np.array([float(values[name]) for name in self._names], dtype=float)

        arr = np.asarray(values, dtype=float).ravel()
        if arr.size != self.dimension:
            raise ValueError(f"Expected {self.dimension} parameters, got {arr.size}")
        return arr

    def mapping_from(self, values):
        """
        Convert mapping/vector values to canonical `{name: value}` mapping.
        """
        vec = self.vector_from(values)
        return {name: float(vec[i]) for i, name in enumerate(self._names)}

    def contains(self, values):
        """
        Check if all values lie inside parameter bounds.
        """
        vec = self.vector_from(values)
        return bool(np.all(vec >= self._lower) and np.all(vec <= self._upper))

    def clip(self, values):
        """
        Clip values to parameter bounds and return a vector.
        """
        vec = self.vector_from(values)
        return np.minimum(np.maximum(vec, self._lower), self._upper)
