"""Shared normalizers for ``[flow.sinks_sources]`` payloads."""

from __future__ import annotations

from numbers import Real

_FIRST_CLIM_KEYWORDS: frozenset[str] = frozenset({"mean", "first"})


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
