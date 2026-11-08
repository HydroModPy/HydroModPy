"""A small frozen ``Model`` for the unit tests of the backends and the factories.

``make_model(**members)`` fills every member the test leaves out: a regular mesh
of two rows and three columns of 10 m cells, no domain, no property, no
boundary, no sink or source, a start at the top, a steady run without a time
grid, and the defaults of ``[solver]``. ``time_grid(*days)`` gives a grid of
periods of the given lengths in days.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import numpy as np

from hydromodpy.model.boundaries.boundary_condition_registry import BoundaryConditionBundle
from hydromodpy.model.initial.state import HeadRule
from hydromodpy.model.model import Geometry, Model, ModelOptions, ModelTime, Properties
from hydromodpy.solver.base.solver_config import SolverConfig
from tests._helpers.regular_cell_meshes import regular_cell_mesh

SECONDS_PER_DAY = 86400.0


def small_geometry() -> Geometry:
    """Two rows and three columns of 10 m cells, without domain, DEM or catchment."""
    return Geometry(
        cells=regular_cell_mesh(xmin=0.0, ymin=0.0, dx=10.0, dy=10.0, nrow=2, ncol=3),
        domain=None,
    )


def time_grid(*days: float) -> SimpleNamespace:
    """A time grid of periods of ``days`` each, without dates."""
    return SimpleNamespace(
        period_lengths_seconds=np.asarray(days, dtype=float) * SECONDS_PER_DAY,
        nstp_per_period=1,
        window=None,
        boundaries=(),
    )


def default_options() -> ModelOptions:
    """The four ``[solver]`` settings at their defaults."""
    return ModelOptions.from_settings(SolverConfig())


def make_model(**members: Any) -> Model:
    """A ``Model`` with the given members, the others filled as the module says."""
    filled: dict[str, Any] = {
        "geometry": small_geometry(),
        "properties": Properties(profiles={}),
        "boundaries": BoundaryConditionBundle(conditions={}, active_ids=()),
        "recharge": None,
        "etp": None,
        "wells": {},
        "lakes": {},
        "sfr": {},
        "flow_barriers": {},
        "active_sinks_sources": (),
        "initial": HeadRule("top"),
        "time": ModelTime(grid=None, regime="steady", first_period_steady=True),
        "options": default_options(),
    }
    filled.update(members)
    return Model(**filled)


__all__ = ["default_options", "make_model", "small_geometry", "time_grid"]
