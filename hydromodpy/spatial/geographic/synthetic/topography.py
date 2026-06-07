"""Analytical topography laws for synthetic geographic contexts."""

from __future__ import annotations

import numpy as np

from hydromodpy.spatial.geographic.synthetic.config import (
    FlatTopography,
    LinearTopography,
    RadialIslandTopography,
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


def _cell_center_coordinates(grid: SyntheticGridConfig) -> tuple[np.ndarray, np.ndarray]:
    """Return x/y meshgrids evaluated at structured-cell centers."""
    x = float(grid.xmin) + (np.arange(int(grid.ncol), dtype=float) + 0.5) * float(grid.dx)
    y = float(grid.ymin) + (np.arange(int(grid.nrow), dtype=float) + 0.5) * float(grid.dy)
    return np.meshgrid(x, y)


def _flat_law(
    config: FlatTopography,
    grid: SyntheticGridConfig,
) -> np.ndarray:
    """Build one constant-elevation surface."""
    return np.full(
        (int(grid.nrow), int(grid.ncol)),
        float(config.base_elevation),
        dtype=float,
    )


def _linear_law(
    config: LinearTopography,
    grid: SyntheticGridConfig,
) -> np.ndarray:
    """Build one linear surface rising from right to left."""
    coord = _right_to_left_coordinate(grid)
    return float(config.base_elevation) + float(config.right_to_left_amplitude) * coord


def _radial_island_law(
    config: RadialIslandTopography,
    grid: SyntheticGridConfig,
) -> np.ndarray:
    """Build one circular island with a steep coastal relief above sea level."""
    xx, yy = _cell_center_coordinates(grid)
    center_x = (
        float(config.center_x)
        if config.center_x is not None
        else 0.5 * (float(grid.xmin) + float(grid.xmax))
    )
    center_y = (
        float(config.center_y)
        if config.center_y is not None
        else 0.5 * (float(grid.ymin) + float(grid.ymax))
    )
    radius = (
        float(config.island_radius)
        if config.island_radius is not None
        else 0.35 * min(float(grid.length_x), float(grid.length_y))
    )

    rr = np.sqrt((xx - center_x) ** 2 + (yy - center_y) ** 2)
    normalized_radius = np.maximum(0.0, 1.0 - (rr / radius) ** 2)
    land_elevation = float(config.crest_elevation) * np.sqrt(normalized_radius)
    ocean_floor = np.full_like(land_elevation, float(config.base_elevation), dtype=float)
    return np.where(rr <= radius, land_elevation, ocean_floor)


def build_topography_values(
    *,
    topography: SyntheticTopographyConfig,
    grid: SyntheticGridConfig,
) -> np.ndarray:
    """Evaluate the requested topography law on one structured support."""
    if isinstance(topography, FlatTopography):
        return np.asarray(_flat_law(topography, grid), dtype=float)
    if isinstance(topography, LinearTopography):
        return np.asarray(_linear_law(topography, grid), dtype=float)
    if isinstance(topography, RadialIslandTopography):
        return np.asarray(_radial_island_law(topography, grid), dtype=float)
    raise ValueError(f"Unsupported synthetic topography variant: {type(topography).__name__}.")
