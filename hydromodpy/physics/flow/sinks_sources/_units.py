"""Shared normalizers for ``[flow.sinks_sources]`` payloads."""

from __future__ import annotations

from numbers import Real

_SPATIAL_MODES: frozenset[str] = frozenset({"auto", "homogeneous", "heterogeneous"})
_INTERPOLATION_METHODS: frozenset[str] = frozenset({"nearest", "linear", "idw"})
_FIRST_CLIM_KEYWORDS: frozenset[str] = frozenset({"mean", "first"})


def normalize_spatial_mode(value: object) -> str:
    """Validate and lowercase a ``spatial_mode`` payload."""
    text = str(value).strip().lower()
    if text not in _SPATIAL_MODES:
        raise ValueError("spatial_mode must be 'auto', 'homogeneous', or 'heterogeneous'.")
    return text


def normalize_interpolation_method(value: object) -> str:
    """Validate and lowercase an ``interpolation_method`` payload."""
    text = str(value).strip().lower()
    if text not in _INTERPOLATION_METHODS:
        raise ValueError("interpolation_method must be 'nearest', 'linear', or 'idw'.")
    return text


def normalize_first_clim(value: object) -> str | float:
    """Normalize a ``first_clim`` policy: 'mean'/'first' or a numeric scalar."""
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized not in _FIRST_CLIM_KEYWORDS:
            raise ValueError("first_clim must be 'mean', 'first', or a numeric value.")
        return normalized
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TypeError("first_clim must be 'mean', 'first', or a numeric value.")
    return float(value)
