"""The ``[geographic.crossings]`` table, the cut of road and rail embankments out of the ground."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.config_kit.visible_when import VisibleWhen
from hydromodpy.core.tracking import InputFile
from hydromodpy.core.units import LengthMeters

__all__ = [
    "CrossingNotchConfig",
]


class CrossingNotchConfig(HydroModelBase):
    """Cut the embankments of roads, railways and bridges out of the ground.

    A DEM shows the embankment of a road across a valley as a wall: the flow
    routing then fills behind it or digs through it, and the model top carries
    the wall into the aquifer. The notch lowers the DEM along the channel at each
    crossing to the bed level read on both sides of the structure, and nowhere
    else. It is a correction of the ground: the routing chain and the model top
    both start from the notched ground.

    The notch follows the channel tree of ``[geographic.river_network]``, which
    is delineated a first time on the ground, notched, and delineated again.
    Weirs and dams are not notched: a weir is a drop of the bed, not a wall. A
    road laid on a dam crest is not notched either: a crossing with a dam or a
    weir of the file within ``snap_radius``, or a ``[geographic.enforce_lakes]``
    polygon on its channel reach is left alone and reported as ``dam_or_weir``.
    """

    enabled: Annotated[bool, Profile.USER] = Field(
        default=False,
        description=(
            "Notch the ground at the crossings of the channel tree with the "
            "declared structures, then delineate again on the notched ground. "
            "Needs [geographic.river_network] enabled."
        ),
    )
    path: Annotated[
        Path | None,
        Profile.USER,
        InputFile(role="crossings_notch", category="geometry"),
        VisibleWhen("enabled", True),
    ] = Field(
        default=None,
        description=(
            "Vector file of the structures, with the columns 'kind', 'source', "
            "'name' and 'drop_m' of the crossings data variable. When left empty "
            "and enabled, it is filled from [[data.crossings.sources]], so the "
            "structures are named once. Required when enabled, from one of the "
            "two."
        ),
    )
    kinds: Annotated[list[Literal["road", "railway", "bridge"]], Profile.USER] = Field(
        default_factory=lambda: ["road", "railway", "bridge"],
        min_length=1,
        description=("Structure kinds to notch. Weirs and dams are never notched."),
    )
    notch_width: Annotated[LengthMeters, Profile.USER] = Field(
        default=10.0,
        gt=0.0,
        description=(
            "Width of the notch across the embankment, in metres. The channel pixel "
            "itself is always lowered, so a width below the cell size cuts one "
            "pixel. The width is applied along the embankment only, the run of "
            "channel pixels that stand above the bed line, never to the two pixels "
            "where the bed is read. Accepts inline units (e.g. 10, '10 m')."
        ),
    )
    bed_reach: Annotated[LengthMeters, Profile.USER] = Field(
        default=50.0,
        gt=0.0,
        description=(
            "Distance along the channel, on each side of the crossing, where the "
            "bed level is read, in metres. The embankment is assumed narrower "
            "than twice this. The notch is the straight line between the two bed "
            "levels. A bed end that falls on the embankment of another crossing is "
            "read further along the channel, beyond it. Accepts inline units "
            "(e.g. 50, '50 m')."
        ),
    )
    max_depth: Annotated[LengthMeters, Profile.USER] = Field(
        default=3.0,
        gt=0.0,
        description=(
            "Largest lowering of any pixel, in metres. A pixel that would be "
            "lowered more is lowered by this and counted as capped in the "
            "report: the embankment is then higher than the cap allows for, "
            "or the crossing sits on a ridge. Accepts inline units (e.g. 3, "
            "'3 m')."
        ),
    )
    snap_radius: Annotated[LengthMeters, Profile.USER] = Field(
        default=30.0,
        gt=0.0,
        description=(
            "A point structure (a bridge of the ROE) farther than this from the "
            "channel tree is ignored, and so is a channel pixel farther than "
            "this from its crossing, in metres. A dam or a weir of the file "
            "within this distance of a crossing stops its notch. "
            "Accepts inline units (e.g. 30, '30 m')."
        ),
    )
