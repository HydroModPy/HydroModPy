"""Hydrometry manager: custom chronicles and Hub'Eau."""

from __future__ import annotations

from hydromodpy.data.managers.base_manager_variable import BaseVariableManager


class HydrometryManager(BaseVariableManager):
    """River discharge and stage records, from the user's files or Hub'Eau."""

    VARIABLE_NAME = "hydrometry"
    INTERNAL_UNIT = "m3/s"
    RECORD_VARIABLE = "discharge"
