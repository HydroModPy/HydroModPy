"""The ``[geographic.bed_regularization]`` table, the fit of the channel bed in the model top."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile

__all__ = [
    "BedRegularizationConfig",
]


class BedRegularizationConfig(HydroModelBase):
    """Least-change regularisation of the channel bed in the model top.

    A DEM read along its own channel rises downstream at many pixels: a deck, a
    hedge, a resampling artefact. A drain or a stream cell on such a rise cannot
    drain into the next one. On the pixels of the generated channel tree only,
    the regularisation fits the bed closest to the ground in least squares that
    never rises downstream (the isotonic regression on a tree of Pardalos and
    Xue, 1999), raising and lowering alike, then gives every pooled flat a
    minimum drop centred on its level. The pixels a crossing notch lowered are
    gaps: interpolated along the channel, never pulling the fit. A declared
    weir or dam cuts the tree, so its drop is kept, and a declared lake is left
    out with its surface.

    It writes a regularised copy of the ground, and the model top and the SFR
    bed read it, so drains and stream reaches see one bed. The routing DEM, the
    channel tree, the catchment and the mesh never read that copy.
    """

    enabled: Annotated[bool, Profile.USER] = Field(
        default=False,
        description=(
            "Regularise the channel bed of the model top: the least-change fit of "
            "the ground that never rises downstream along the channel tree, with "
            "the crossing notches as gaps and the declared weirs and dams as "
            "drops. Needs [geographic.river_network] enabled."
        ),
    )
    min_slope: Annotated[float, Profile.USER] = Field(
        default=1.0e-4,
        ge=0.0,
        description=(
            "Minimum drop of the fitted bed per metre along the channel (m/m), "
            "given to the flats the fit pools. The SFR default slope."
        ),
        json_schema_extra={"unit": "-"},
    )
