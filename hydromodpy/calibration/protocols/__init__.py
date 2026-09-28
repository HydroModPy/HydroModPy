"""Named calibration protocols.

A protocol is a published calibration method a file names instead of retyping:
it writes the stages, their criteria and the model regimes they need. See
:mod:`hydromodpy.calibration.protocols.base` for the contract and
:mod:`hydromodpy.calibration.protocols.registry` for what is registered.
"""

from hydromodpy.calibration.protocols.base import CalibrationProtocol, Reference
from hydromodpy.calibration.protocols.matching_hydrographic_network import (
    MatchingHydrographicNetwork,
    options_the_recipe_already_runs,
    why_the_spin_up_year_is_scored,
)
from hydromodpy.calibration.protocols.registry import (
    WRITTEN_SECTIONS,
    available_protocols,
    expand_calibration_protocol,
    get_protocol,
    protocol_options_away_from_the_recipe,
    protocol_record,
)

__all__ = [
    "WRITTEN_SECTIONS",
    "CalibrationProtocol",
    "MatchingHydrographicNetwork",
    "Reference",
    "available_protocols",
    "expand_calibration_protocol",
    "get_protocol",
    "options_the_recipe_already_runs",
    "protocol_options_away_from_the_recipe",
    "protocol_record",
    "why_the_spin_up_year_is_scored",
]
