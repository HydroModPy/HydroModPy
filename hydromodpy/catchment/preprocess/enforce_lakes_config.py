"""The ``[geographic.enforce_lakes]`` table, the lake footprints the ground corrections leave alone."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, ClassVar

from pydantic import Field

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.config_kit.visible_when import VisibleWhen
from hydromodpy.core.tracking.input_file import InputFile


class LakeEnforcementConfig(HydroModelBase):
    """Lake footprint polygons that the ground corrections leave alone.

    The routing DEM is no longer carved at the lakes: the cell drainage ``D``
    already makes the water cross a lake, and the carve (a ramp toward the
    outlet, an outlet notch, a stream capture) moved neither the basin, the
    network nor the drains. The polygons stay a declared input for the two
    steps that read them, the crossing notch and the bed regularization.
    """

    model_refused_keys: ClassVar[Mapping[str, str]] = {
        "slope": "the lake ramp of the routing DEM is removed, D already crosses the lake",
        "buffer_m": "the lake ramp of the routing DEM is removed, D already crosses the lake",
        "capture_radius_m": (
            "the stream capture is removed, D already crosses the lake; "
            "raise flow.sinks_sources.sfr.<id>.lake_feeder_snap to feed a lake from a "
            "dead-end reach"
        ),
        "capture_max_streams": "the stream capture is removed, D already crosses the lake",
        "capture_min_acc_fraction": "the stream capture is removed, D already crosses the lake",
    }

    enabled: Annotated[bool, Profile.USER] = Field(
        default=False,
        description=(
            "Read the lake footprint polygons of lake_geometry_path as lakes of the "
            "ground, so the crossing notch and the bed regularisation leave them alone."
        ),
    )
    lake_geometry_path: Annotated[
        Path | None,
        Profile.USER,
        InputFile(role="lake_enforcement_geometry", category="geometry"),
        VisibleWhen("enabled", True),
    ] = Field(
        default=None,
        description=(
            "Lake footprint polygons (gpkg/shp). A bare filename resolves "
            "against <workspace>/data/lake_geometry/. Required when enabled."
        ),
    )
