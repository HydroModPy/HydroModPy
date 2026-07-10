"""Solver-agnostic input/output contract for surface conditioning.

The conditioning kernel is a pure function of the ``spatial`` layer: it takes
primitives (per-cell top, active mask, face adjacency, optional floor and fixed
control levels) and returns a conditioned top. It holds no solver type and no
flopy import, so every backend (MODFLOW 6 DISV, structured, MODFLOW-NWT,
Boussinesq, a future DISU) can feed it by extracting these primitives from its
native discretization and writing the returned top back.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

import numpy as np


@dataclass(frozen=True)
class SurfaceConditioningInput:
    """Primitives the conditioning kernel operates on (zero solver type)."""

    top: np.ndarray
    """(n_cells,) surface elevation per cell."""

    active: np.ndarray
    """(n_cells,) bool: cells that participate in the drainage graph."""

    adjacency: list[set[int]]
    """cell -> set of face-adjacent neighbour cell ids (shared-edge)."""

    floor: np.ndarray | None = None
    """(n_cells,) lower bound (e.g. botm0 + min_thickness); top must stay above it."""

    control_cells: Mapping[int, float] = field(default_factory=dict)
    """cell -> fixed base level (lake bed, thalweg): pinned, never raised."""


@dataclass(frozen=True)
class SurfaceConditioningResult:
    """Conditioned top plus a per-cell raise mask and a summary."""

    top: np.ndarray
    """(n_cells,) conditioned surface elevation per cell."""

    raised: np.ndarray
    """(n_cells,) bool: cells whose top the fill lifted."""

    info: dict[str, float]
    """cells_raised, max_raise_m, mean_raise_m, unreached_active, floor_violations."""
