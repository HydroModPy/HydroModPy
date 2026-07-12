"""Pydantic configuration for the ``[spinup]`` cyclic spin-up section.

The cyclic spin-up repeats a representative forcing window, restarting each
cycle from the previous cycle's state, until the aquifer heads and the lake
stage stop changing between cycles. The converged state is a reusable antecedent
that a production run (or every calibration trial) seeds through
``[flow] restart_from``. This section only holds the loop settings; the driver
lives in ``hydromodpy/project/spinup.py``.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile


class SpinupConfig(HydroModelBase):
    """Settings for the cyclic spin-up loop (``[spinup]``)."""

    max_cycles: Annotated[int, Profile.USER] = Field(
        default=10,
        ge=1,
        description="Maximum spin-up cycles before the loop stops without converging.",
    )
    tol_head: Annotated[float, Profile.USER] = Field(
        default=0.01,
        gt=0.0,
        description=(
            "Head convergence tolerance [m]. The loop converges when the largest "
            "absolute head change between two cycles (L-inf over active cells) is "
            "below this."
        ),
    )
    tol_stage: Annotated[float, Profile.USER] = Field(
        default=0.01,
        gt=0.0,
        description=(
            "Lake-stage convergence tolerance [m]. The loop converges when the "
            "largest absolute stage change between two cycles, over every lake, is "
            "below this. Ignored when the model has no lake."
        ),
    )
    window_start: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description=(
            "Cycle window start (ISO datetime, e.g. '2019-01-01'). The representative "
            "forcing period each cycle repeats. None reuses [simulation.time]."
        ),
    )
    window_end: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description=(
            "Cycle window end (ISO datetime). None reuses [simulation.time]. Set both "
            "window bounds to spin up on a shorter representative period than the "
            "production chronicle."
        ),
    )
