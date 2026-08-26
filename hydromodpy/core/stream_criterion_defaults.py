"""The numeric defaults of the stream-network criterion, in one Pydantic model.

Two layers read the same criterion and neither may import the other: a
calibration scores it per trial, and the results layer rebuilds it from a
finished run so a figure cannot contradict the numbers it illustrates. Both may
import ``core``, so this is the only place a default can live without being
written twice, and a threshold written twice is a map that drifts from its own
caption.

Nothing here changes what is computed. ``tau_specific_ratio`` selects the
seepage threshold, the other three decide only what gets logged.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile


class StreamCriterionDefaults(HydroModelBase):
    """Defaults shared by the calibration criterion and its redrawn figures."""

    tau_specific_ratio: Annotated[float, Profile.EXPERT] = Field(
        default=1.0e-4,
        ge=0.0,
        description=(
            "Fraction of its own recharge below which a releasing cell is not a "
            "stream. A SPECIFIC flux, not a discharge: on a mesh of uneven cells a "
            "fixed m3/s cut would be nine times harsher on a cell three times "
            "smaller and the network would follow the refinement rather than the "
            "physics. 0.0 reproduces the purely geometric criterion of the paper."
        ),
    )
    alpha_warning_threshold: Annotated[float, Profile.EXPERT] = Field(
        default=0.90,
        gt=0.0,
        le=1.0,
        description=(
            "Below this value of the catchment-restricted agreement between the "
            "mapped network and the model top, the run says its distances carry a "
            "top-versus-map disagreement on top of the hydrogeology. Logging only."
        ),
    )
    clipping_warning_share: Annotated[float, Profile.EXPERT] = Field(
        default=0.10,
        ge=0.0,
        le=1.0,
        description=(
            "Share of the mapped stream cells outside the delineated catchment above "
            "which the whole-mesh agreement is reported as unreadable. Those reaches "
            "trace through the buffer, where no cell is required to descend into the "
            "network. Logging only."
        ),
    )
    clipping_warning_gap: Annotated[float, Profile.EXPERT] = Field(
        default=0.05,
        ge=0.0,
        le=1.0,
        description=(
            "Minimum absolute gap between the whole-mesh and the catchment agreement "
            "for the clipping report to fire. A linework spilling out of the "
            "catchment over ground that routes the same way leaves the two equal, "
            "and reporting it there would be noise on every project. Logging only."
        ),
    )


STREAM_CRITERION_DEFAULTS = StreamCriterionDefaults()
"""The one instance every layer reads, so a default exists in a single object."""


__all__ = ["STREAM_CRITERION_DEFAULTS", "StreamCriterionDefaults"]
