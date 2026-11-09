"""Lake-withdrawal variable: custom chronicles."""

from __future__ import annotations

from hydromodpy.data.families.stations import StationVariable


class LakeWithdrawalVariable(StationVariable):
    VARIABLE_NAME = "lake_withdrawal"
    INTERNAL_UNIT = "m3/s"
