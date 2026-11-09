"""Settings of the linear reservoir, ``[solver.linear_reservoir]``.

One field: the time constant of the exponential the kernel advances. It
carries no default that could pass for physics, so a table that omits it
is refused when it is read.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.calibrable import Calibrable
from hydromodpy.core.config_kit.field_metadata import field_metadata
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.units.types import DurationDays


class LinearReservoirOptions(HydroModelBase):
    """What ``[solver.linear_reservoir]`` holds.

    ``time_constant`` sets how much of the recharge the state still holds one
    time constant after it fell. A bare number reads in days, ``"30 days"``
    reads too. The search walks it in the log space (QA A1), so the class
    declares no bounds: the calibration of one site states them.
    """

    time_constant: Annotated[
        DurationDays,
        Profile.USER,
        Field(
            gt=0.0,
            description=(
                "Time constant of the reservoir, in days: how much of the water "
                "the state holds falls back in one time constant. A bare number "
                'reads in days; "30 days" also reads. Refused when omitted.'
            ),
            json_schema_extra=field_metadata(
                calibrable=Calibrable(search_space="log", sampling="log_uniform", units="day"),
            ),
        ),
    ]


__all__ = ["LinearReservoirOptions"]
