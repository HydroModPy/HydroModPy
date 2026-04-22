# -*- coding: utf-8 -*-
"""
* Copyright (C) 2023-2025 Alexandre Gauvain, Ronan Abhervé, Jean-Raynald de Dreuzy
*
* This program and the accompanying materials are made available under the
* terms of the Eclipse Public License 2.0 which is available at
* http://www.eclipse.org/legal/epl-2.0, or the Apache License, Version 2.0
* which is available at https://www.apache.org/licenses/LICENSE-2.0.
*
* SPDX-License-Identifier: EPL-2.0 OR Apache-2.0
"""

"""Grid diagnostics for MODFLOW-NWT pre-processing."""

import numpy as np

from hydromodpy.core.logging import get_logger

logger = get_logger(__name__)


def check_water_flow_connectivity(
    grid: np.ndarray,
) -> list[tuple[int, int, int]]:
    """
    Check layer-to-layer water flow connectivity across the MODFLOW grid.

    For each active cell, verifies that its elevation range overlaps with at
    least one adjacent neighbour in the same layer. Cells where no overlap
    exists cannot exchange water horizontally and are reported as problematic.

    Parameters
    ----------
    grid : np.ndarray
        3-D array of shape ``(layers, rows, cols)`` containing top/bottom
        elevations of the MODFLOW grid (e.g. ``mf.modelgrid.top_botm``).

    Returns
    -------
    list[tuple[int, int, int]]
        List of ``(layer, row, col)`` indices of problematic cells.
        Empty list when all cells are connected.
    """
    layers, rows, cols = grid.shape
    problematic_cells: list[tuple[int, int, int]] = []

    for z in range(layers - 1):
        logger.debug("Checking layer %d", z)
        for y in range(rows):
            for x in range(cols):
                if np.isnan(grid[z, y, x]) or np.isnan(grid[z + 1, y, x]):
                    continue

                current_top = grid[z, y, x]
                current_bottom = grid[z + 1, y, x]

                neighbors: list[tuple[float, float]] = []

                if y > 0 and not (
                    np.isnan(grid[z, y - 1, x]) or np.isnan(grid[z + 1, y - 1, x])
                ):
                    neighbors.append((grid[z, y - 1, x], grid[z + 1, y - 1, x]))
                if y < rows - 1 and not (
                    np.isnan(grid[z, y + 1, x]) or np.isnan(grid[z + 1, y + 1, x])
                ):
                    neighbors.append((grid[z, y + 1, x], grid[z + 1, y + 1, x]))
                if x > 0 and not (
                    np.isnan(grid[z, y, x - 1]) or np.isnan(grid[z + 1, y, x - 1])
                ):
                    neighbors.append((grid[z, y, x - 1], grid[z + 1, y, x - 1]))
                if x < cols - 1 and not (
                    np.isnan(grid[z, y, x + 1]) or np.isnan(grid[z + 1, y, x + 1])
                ):
                    neighbors.append((grid[z, y, x + 1], grid[z + 1, y, x + 1]))

                if neighbors:
                    can_flow = any(
                        current_bottom <= n_top and current_top >= n_bottom
                        for n_top, n_bottom in neighbors
                    )
                    if not can_flow:
                        problematic_cells.append((z, y, x))

    return problematic_cells
