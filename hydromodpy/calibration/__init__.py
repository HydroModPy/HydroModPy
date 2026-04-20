"""Calibration sub-system.

Public surface:
    - CalibrationEngine: the orchestrator
    - Optimizer / Objective / Evaluator: Protocol contracts
    - Calibrable: Pydantic-field annotation marking a calibrable parameter
    - discover_calibrable: auto-discover calibrable fields in a config tree
    - build_optimizer: adapter registry lookup
"""

from hydromodpy.calibration.optimizer import (
    Optimizer,
    ParamSuggestion,
    EvaluationResult,
    build_optimizer,
    register_optimizer,
)
from hydromodpy.calibration.objective import (
    Objective,
    ObjectiveValue,
    ObservationSet,
    SimulationOutput,
    ScalarObjective,
)
from hydromodpy.calibration.parameters import (
    Calibrable,
    CalibParameter,
    ParameterSpace,
    discover_calibrable,
)
from hydromodpy.calibration.engine import CalibrationEngine, CalibrationSession

__all__ = [
    "CalibrationEngine",
    "CalibrationSession",
    "Optimizer",
    "Objective",
    "ObjectiveValue",
    "ObservationSet",
    "SimulationOutput",
    "ScalarObjective",
    "Calibrable",
    "CalibParameter",
    "ParameterSpace",
    "ParamSuggestion",
    "EvaluationResult",
    "build_optimizer",
    "register_optimizer",
    "discover_calibrable",
]
