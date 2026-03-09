"""Analytical topography laws for synthetic geographic contexts."""

from __future__ import annotations

from collections.abc import Callable

import numpy as np

from hydromodpy.geographic_synthethic.config import (
    SyntheticGridConfig,
    SyntheticTopographyConfig,
)


def _right_to_left_coordinate(grid: SyntheticGridConfig) -> np.ndarray:
    """Return a normalized 2-D coordinate equal to 0 on the right and 1 on the left."""
    if int(grid.ncol) == 1:
        profile = np.zeros((1,), dtype=float)
    else:
        profile = np.linspace(1.0, 0.0, int(grid.ncol), dtype=float)
    return np.broadcast_to(profile, (int(grid.nrow), int(grid.ncol))).copy()


def _flat_law(
    config: SyntheticTopographyConfig,
    grid: SyntheticGridConfig,
) -> np.ndarray:
    """Build one constant-elevation surface."""
    return np.full(
        (int(grid.nrow), int(grid.ncol)),
        float(config.base_elevation),
        dtype=float,
    )


def _linear_law(
    config: SyntheticTopographyConfig,
    grid: SyntheticGridConfig,
) -> np.ndarray:
    """Build one linear surface rising from right to left."""
    coord = _right_to_left_coordinate(grid)
    return float(config.base_elevation) + float(config.right_to_left_amplitude) * coord


_TOPOGRAPHY_LAWS: dict[str, Callable[[SyntheticTopographyConfig, SyntheticGridConfig], np.ndarray]] = {
    "flat": _flat_law,
    "linear": _linear_law,
}


def build_topography_values(
    *,
    topography: SyntheticTopographyConfig,
    grid: SyntheticGridConfig,
) -> np.ndarray:
    """Evaluate the requested topography law on one structured support."""
    law = _TOPOGRAPHY_LAWS.get(str(topography.kind).strip().lower())
    if law is None:
        supported = ", ".join(sorted(_TOPOGRAPHY_LAWS))
        raise ValueError(
            f"Unsupported synthetic topography kind={topography.kind!r}. "
            f"Supported values: {supported}."
        )
    return np.asarray(law(topography, grid), dtype=float)
