"""Criteria: what turns evidence into a cost, and says what it needs to do so.

See :mod:`hydromodpy.calibration.criteria.base` for the contract and
:mod:`hydromodpy.calibration.criteria.registry` for what is registered.
"""

from hydromodpy.calibration.criteria.base import (
    Criterion,
    CriterionRequirements,
    CriterionResult,
    Validity,
)
from hydromodpy.calibration.criteria.hydrographic_network_distance import (
    HydrographicNetworkDistance,
    distance_pair,
)
from hydromodpy.calibration.criteria.registry import (
    NETWORK_ESTIMATORS,
    available_criteria,
    criterion_for,
)
from hydromodpy.calibration.criteria.series import SeriesCriterion

__all__ = [
    "NETWORK_ESTIMATORS",
    "Criterion",
    "CriterionRequirements",
    "CriterionResult",
    "HydrographicNetworkDistance",
    "SeriesCriterion",
    "Validity",
    "available_criteria",
    "criterion_for",
    "distance_pair",
]
