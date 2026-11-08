"""The ``Model`` the LAK builder reads, for the lake cases that drive MODFLOW 6 by hand."""

from __future__ import annotations

from collections.abc import Mapping

from hydromodpy.model.boundaries.boundary_condition_registry import BoundaryConditionBundle
from hydromodpy.model.initial.state import HeadRule
from hydromodpy.model.model import Geometry, Model, ModelOptions, ModelTime, Properties
from hydromodpy.solver.base.solver_config import SolverConfig


def lake_inputs(lakes: Mapping[str, object]) -> Model:
    """A model whose only active package is LAK, with the lake tables ``lakes``.

    The cells, the time grid and the other members are absent: the case builds
    the grid and the periods with flopy itself.
    """
    return Model(
        geometry=Geometry(cells=None, domain=None),
        properties=Properties(profiles={}),
        boundaries=BoundaryConditionBundle(conditions={}, active_ids=("lake",)),
        recharge=None,
        etp=None,
        wells={},
        lakes=lakes,
        sfr={},
        flow_barriers={},
        active_sinks_sources=(),
        initial=HeadRule("top"),
        time=ModelTime(grid=None, regime="steady", first_period_steady=True),
        options=ModelOptions.from_settings(SolverConfig()),
    )


__all__ = ["lake_inputs"]
