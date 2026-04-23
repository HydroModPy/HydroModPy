"""Calibration sub-system.

Public surface:
    - CalibrationEngine: the orchestrator
    - Optimizer / Objective / Evaluator: Protocol contracts
    - Calibrable: Pydantic-field annotation marking a calibrable parameter
    - discover_calibrable: auto-discover calibrable fields in a config tree
    - build_optimizer: adapter registry lookup
"""

from hydromodpy.calibration.engine import CalibrationEngine, CalibrationSession
from hydromodpy.calibration.objective import (
    CompositeObjective,
    Objective,
    ObjectiveValue,
    ObservationSet,
    ScalarObjective,
    SimulationOutput,
)
from hydromodpy.calibration.optimizer import (
    EvaluationResult,
    Optimizer,
    ParamSuggestion,
    build_optimizer,
    register_optimizer,
)
from hydromodpy.calibration.parameters import (
    CalibParameter,
    Calibrable,
    ParameterSpace,
    discover_calibrable,
)

__all__ = [
    "CalibrationEngine",
    "CalibrationSession",
    "Optimizer",
    "Objective",
    "ObjectiveValue",
    "ObservationSet",
    "SimulationOutput",
    "ScalarObjective",
    "CompositeObjective",
    "Calibrable",
    "CalibParameter",
    "ParameterSpace",
    "ParamSuggestion",
    "EvaluationResult",
    "build_optimizer",
    "register_optimizer",
    "discover_calibrable",
]
