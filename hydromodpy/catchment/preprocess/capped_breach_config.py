"""The ``[geographic.capped_breach]`` table, the limits of the capped breach of the DEM."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from hydromodpy.catchment.terrain.port import CappedBreach
from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.units.types import LengthMeters

__all__ = [
    "CappedBreachConfig",
]


def capped_breach_of(geographic: object) -> CappedBreach | None:
    """Return the capped-breach limits one geographic object selects, else ``None``.

    Reads ``dem_correc_type`` and ``capped_breach`` off a ``GeographicConfig`` or
    off the ``CatchmentDelineation`` that carries the same two attributes, so a
    solver rebuilding its routing rasters conditions the DEM as the delineation
    did. A ``capped_breach`` run with no section uses the defaults of the
    section, which is what the configuration documents.
    """
    if str(getattr(geographic, "dem_correc_type", "")) != "capped_breach":
        return None

    section = getattr(geographic, "capped_breach", None) or CappedBreachConfig()
    return CappedBreach(
        max_depth_m=float(section.max_depth), max_distance_m=float(section.max_distance)
    )


class CappedBreachConfig(HydroModelBase):
    """Limits of the ``capped_breach`` DEM conditioning, in meters.

    Read only when ``[geographic] dem_correc_type = "capped_breach"``. Least-cost
    breaching digs a path through the barrier that closes a depression. These two
    limits bound that digging, and whatever they refuse is filled instead. Both
    are given in meters but the tool counts along the cells of a path (a sum of
    lowerings, a number of cells), so a given value does not mean the same thing
    at every grid resolution: see each field.
    """

    max_depth: Annotated[LengthMeters, Profile.USER] = Field(
        default=0.5,
        gt=0.0,
        description=(
            "Largest cumulative lowering, in metres, of one breach path (the "
            "'max_cost' of Whitebox): the lowering summed over the cells of the "
            "path, not the depth of one cell. With short paths the realised maximum "
            "lowering of a cell stays close to it. On a finer grid a thick embankment "
            "spreads the cost over more cells, so it is filled instead of dug: the "
            "same value does not give the same landscape at every resolution. A "
            "depression whose cheapest breach costs more is filled. Paths overlap, so "
            "the lowering of a cell can exceed it (0.56 m for a value of 0.5 m, on a "
            "75 m grid). The realised depth is measured after the call, logged, and "
            "warned about when it exceeds this value. Accepts inline units (e.g. 0.5, "
            "'0.5 m')."
        ),
    )
    max_distance: Annotated[LengthMeters, Profile.USER] = Field(
        default=200.0,
        gt=0.0,
        description=(
            "Longest breach path, in metres. Translated to the DEM grid as "
            "ceil(max_distance / cell size) cells, at least one, and counted in "
            "cells along the path: a diagonal step counts one cell, so a diagonal "
            "breach can be up to 1.41 times longer than max_distance. A depression "
            "with no way out within this length is filled. Accepts inline units "
            "(e.g. 200, '0.2 km')."
        ),
    )
