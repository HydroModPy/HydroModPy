"""Hydrometry variable: custom chronicles and Hub'Eau.

``HydrometryVariable`` dispatches to the configured source (``custom`` or ``hubeau``). Its
config models forbid extra keys.
"""

from __future__ import annotations

from hydromodpy.data.families.stations import StationVariable


class HydrometryVariable(StationVariable):
    """River discharge and stage records, from the user's files or Hub'Eau."""

    VARIABLE_NAME = "hydrometry"
    INTERNAL_UNIT = "m3/s"
    RECORD_VARIABLE = "discharge"
