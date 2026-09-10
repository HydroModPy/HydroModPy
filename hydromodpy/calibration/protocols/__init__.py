"""Named calibration protocols.

A protocol is a published calibration method a file names instead of retyping:
it writes the stages, their criteria and the model regimes they need. See
:mod:`hydromodpy.calibration.protocols.base` for the contract and
:mod:`hydromodpy.calibration.protocols.registry` for what is registered.
"""

from hydromodpy.calibration.protocols.base import CalibrationProtocol, Reference
from hydromodpy.calibration.protocols.matching_hydrographic_network import (
    MatchingHydrographicNetwork,
    MatchingHydrographicNetworkOptions,
)
from hydromodpy.calibration.protocols.registry import (
    available_protocols,
    expand_calibration_protocol,
    get_protocol,
    protocol_record,
)

__all__ = [
    "CalibrationProtocol",
    "MatchingHydrographicNetwork",
    "MatchingHydrographicNetworkOptions",
    "Reference",
    "available_protocols",
    "expand_calibration_protocol",
    "get_protocol",
    "protocol_record",
]
