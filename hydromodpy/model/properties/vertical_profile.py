"""Depth profile of a field parameter: a multiplicative factor f(depth).

A profile is a plain mapping. ``normalize_vertical_profile`` checks what a
caller hands in and returns the canonical mapping that ``FieldParam`` keeps.
The other functions read that canonical mapping. Depth is 0 at the surface
and positive downward.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, get_args

import numpy as np

from hydromodpy.core.config_kit.field_param.sections import VerticalProfileDepthAt
from hydromodpy.core.units.registry import UREG
from hydromodpy.model.properties.mesh_cells import cell_values

SUPPORTED_VERTICAL_PROFILE_MODES = ("none", "exponential", "tabulated")
SUPPORTED_VERTICAL_PROFILE_INTERPOLATIONS = ("linear", "step")
GRADED_KEYS = ("characteristic_depth_high", "ground_low", "ground_high")
"""The keys that grade the decay length of an exponential profile with the ground elevation."""


def _length_to_m(value: object, *, label: str) -> float:
    """Convert a length-like input (number or pint string) to meters."""
    if value is None:
        raise ValueError(f"{label} cannot be None.")
    if isinstance(value, bool):
        raise TypeError(f"{label} rejects boolean input.")
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        token = value.strip()
        if token == "":
            raise ValueError(f"{label}: empty length string is not allowed.")
        quantity = UREG(token)
        if not hasattr(quantity, "magnitude"):
            return float(quantity)
        return float(quantity.to("m").magnitude)
    raise TypeError(f"{label}: unsupported length value type {type(value).__name__}.")


def normalize_vertical_profile(
    vertical_profile: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Check a profile mapping and return its canonical form."""
    if vertical_profile is None:
        return {"kind": "none"}
    if not isinstance(vertical_profile, Mapping):
        raise TypeError("vertical_profile must be a mapping when provided")

    mode = str(vertical_profile.get("kind", "none")).strip().lower()
    if mode not in SUPPORTED_VERTICAL_PROFILE_MODES:
        allowed = ", ".join(SUPPORTED_VERTICAL_PROFILE_MODES)
        raise ValueError(f"Unsupported vertical profile mode '{mode}'. Allowed: {allowed}")

    if mode == "none":
        return {"kind": "none"}
    depth_at = str(vertical_profile.get("depth_at", "middle")).strip().lower()
    if depth_at not in get_args(VerticalProfileDepthAt):
        allowed = ", ".join(get_args(VerticalProfileDepthAt))
        raise ValueError(f"Unsupported vertical_profile depth_at '{depth_at}'. Allowed: {allowed}")
    placed = {} if depth_at == "middle" else {"depth_at": depth_at}

    if mode == "exponential":
        if "characteristic_depth" not in vertical_profile:
            raise KeyError("vertical_profile kind='exponential' requires 'characteristic_depth'")
        characteristic_depth = _length_to_m(
            vertical_profile["characteristic_depth"],
            label="vertical_profile.characteristic_depth",
        )
        if not np.isfinite(characteristic_depth) or characteristic_depth <= 0.0:
            raise ValueError("vertical_profile.characteristic_depth must be > 0")

        min_factor = vertical_profile.get("min_factor")
        if min_factor is not None:
            min_factor = float(min_factor)
            if not np.isfinite(min_factor):
                raise ValueError("vertical_profile.min_factor must be finite when provided")
            if min_factor < 0.0 or min_factor > 1.0:
                raise ValueError("vertical_profile.min_factor must be in [0, 1]")

        normalized = {
            "kind": "exponential",
            "characteristic_depth": characteristic_depth,
        }
        if min_factor is not None:
            normalized["min_factor"] = float(min_factor)
        graded = [key for key in GRADED_KEYS if vertical_profile.get(key) is not None]
        if graded:
            if len(graded) != len(GRADED_KEYS):
                raise KeyError(f"vertical_profile needs {', '.join(GRADED_KEYS)} together")
            high = _length_to_m(vertical_profile["characteristic_depth_high"], label="high")
            low_ground = _length_to_m(vertical_profile["ground_low"], label="ground_low")
            high_ground = _length_to_m(vertical_profile["ground_high"], label="ground_high")
            if not np.isfinite(high) or high <= 0.0:
                raise ValueError("vertical_profile.characteristic_depth_high must be > 0")
            if high_ground <= low_ground:
                raise ValueError("vertical_profile.ground_high must be above ground_low")
            normalized.update(
                characteristic_depth_high=high, ground_low=low_ground, ground_high=high_ground
            )
        return {**normalized, **placed}

    # The mode check above leaves "tabulated" as the only mode here.
    if "depths" not in vertical_profile:
        raise KeyError("vertical_profile kind='tabulated' requires 'depths'")
    if "factors" not in vertical_profile:
        raise KeyError("vertical_profile kind='tabulated' requires 'factors'")

    depths = np.asarray(vertical_profile["depths"], dtype=float).reshape(-1)
    factors = np.asarray(vertical_profile["factors"], dtype=float).reshape(-1)
    if depths.size == 0 or factors.size == 0:
        raise ValueError("vertical_profile tabulated depths/factors cannot be empty")
    if depths.size != factors.size:
        raise ValueError("vertical_profile tabulated depths/factors must have the same length")
    if np.any(~np.isfinite(depths)) or np.any(~np.isfinite(factors)):
        raise ValueError("vertical_profile tabulated depths/factors must be finite")
    if np.any(depths < 0.0):
        raise ValueError("vertical_profile depths must be >= 0")
    if np.any(np.diff(depths) <= 0.0):
        raise ValueError("vertical_profile depths must be strictly increasing")
    if not np.isclose(float(depths[0]), 0.0):
        raise ValueError("vertical_profile tabulated first depth must be 0.0")
    if not np.isclose(float(factors[0]), 1.0):
        raise ValueError("vertical_profile tabulated factor at depth 0.0 must be 1.0")

    interpolation = str(vertical_profile.get("interpolation", "linear")).strip().lower()
    if interpolation not in SUPPORTED_VERTICAL_PROFILE_INTERPOLATIONS:
        allowed = ", ".join(SUPPORTED_VERTICAL_PROFILE_INTERPOLATIONS)
        raise ValueError(
            f"Unsupported vertical_profile interpolation '{interpolation}'. Allowed: {allowed}"
        )

    if any(vertical_profile.get(key) is not None for key in GRADED_KEYS):
        raise ValueError(f"{', '.join(GRADED_KEYS)} grade an exponential profile only")
    return {
        "kind": "tabulated",
        "depths": depths.tolist(),
        "factors": factors.tolist(),
        "interpolation": interpolation,
        **placed,
    }


def normalize_depth(depth):
    """Return depth as a float array, refusing non-finite or negative values."""
    depth_arr = np.asarray(0.0 if depth is None else depth, dtype=float)
    if np.any(~np.isfinite(depth_arr)):
        raise ValueError("depth must contain only finite numeric values")
    if np.any(depth_arr < 0.0):
        raise ValueError("depth values must be >= 0 (0 at surface, positive downward)")
    return depth_arr


def vertical_factor(vertical_profile: Mapping[str, Any], depth=0.0):
    """Return the factor of a canonical profile at ``depth`` (float or array)."""
    depth_arr = normalize_depth(depth)
    mode = str(vertical_profile.get("kind", "none"))

    if mode == "none":
        out = np.ones_like(depth_arr, dtype=float)
    elif mode == "exponential":
        characteristic_depth = float(vertical_profile["characteristic_depth"])
        out = np.exp(-depth_arr / characteristic_depth)
        min_factor = vertical_profile.get("min_factor")
        if min_factor is not None:
            out = np.maximum(out, float(min_factor))
    elif mode == "tabulated":
        depths = np.asarray(vertical_profile["depths"], dtype=float)
        factors = np.asarray(vertical_profile["factors"], dtype=float)
        interpolation = str(vertical_profile.get("interpolation", "linear"))
        if interpolation == "linear":
            out = np.interp(
                depth_arr,
                depths,
                factors,
                left=float(factors[0]),
                right=float(factors[-1]),
            )
        else:
            indices = np.searchsorted(depths, depth_arr, side="right") - 1
            indices = np.clip(indices, 0, depths.size - 1)
            out = factors[indices]
    else:  # pragma: no cover - protected by normalize_vertical_profile
        raise ValueError(f"Unsupported vertical profile mode '{mode}'")

    if np.ndim(depth_arr) == 0:
        return float(np.asarray(out, dtype=float))
    return np.asarray(out, dtype=float)


def layer_profile_depths(vertical_profile: Mapping[str, Any], interfaces) -> np.ndarray:
    """Return the depth at which each layer reads the profile, shape (nlay, n_cells).

    ``interfaces`` is (nlay + 1, n_cells) in m, the ground then the base of each
    layer. ``depth_at`` picks the middle (the default), the top or the base of the
    layer, or ``surface_then_base``: the ground for the first layer and the base for
    the others. A depth is never negative. A graded exponential profile scales the
    depth of each cell by characteristic_depth over the decay length of its ground,
    the length going linearly from ground_low to ground_high, so the factor
    exp(-depth / characteristic_depth) of the profile is exp(-depth / length).
    """
    z = np.asarray(interfaces, dtype=float)
    if z.ndim != 2 or z.shape[0] < 2:
        raise ValueError(f"interfaces must have shape (nlay + 1, n_cells), got {z.shape}")
    ground, tops, bases = z[0], z[:-1], z[1:]
    point = {
        "top": tops,
        "middle": 0.5 * (tops + bases),
        "base": bases,
        "surface_then_base": np.vstack([ground[None, :], bases[1:]]),
    }
    depth = np.maximum(0.0, ground - point[str(vertical_profile.get("depth_at", "middle"))])
    if vertical_profile.get("characteristic_depth_high") is None:
        return depth
    low = float(vertical_profile["characteristic_depth"])
    high = float(vertical_profile["characteristic_depth_high"])
    length = np.interp(
        ground,
        [float(vertical_profile["ground_low"]), float(vertical_profile["ground_high"])],
        [low, high],
    )
    return depth * low / length


def apply_vertical_profile(vertical_profile: Mapping[str, Any], surface_values, *, depth=0.0):
    """Multiply surface values by the profile factor at ``depth``."""
    factor = vertical_factor(vertical_profile, depth)
    if np.ndim(factor) == 0:
        scalar_factor = float(factor)
        values_arr = np.asarray(surface_values, dtype=float)
        if values_arr.ndim == 0:
            return float(values_arr) * scalar_factor
        return values_arr * scalar_factor
    try:
        return np.asarray(surface_values, dtype=float) * np.asarray(factor, dtype=float)
    except ValueError as exc:
        raise ValueError("Depth shape is not broadcastable with surface values shape") from exc


def mesh_vertical_factor(vertical_profile: Mapping[str, Any], mesh, *, depth=0.0):
    """Return the profile factor at ``depth``, one value per mesh cell when depth is an array."""
    factor = vertical_factor(vertical_profile, depth)
    if np.ndim(factor) == 0:
        return float(factor)
    return np.asarray(cell_values(mesh, factor), dtype=float)


__all__ = [
    "SUPPORTED_VERTICAL_PROFILE_INTERPOLATIONS",
    "SUPPORTED_VERTICAL_PROFILE_MODES",
    "apply_vertical_profile",
    "layer_profile_depths",
    "mesh_vertical_factor",
    "normalize_depth",
    "normalize_vertical_profile",
    "vertical_factor",
]
