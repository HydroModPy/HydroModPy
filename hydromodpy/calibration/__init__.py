"""Calibration sub-system.

Public surface:
    - CalibrationEngine: the orchestrator
    - Optimizer / Objective / Evaluator: Protocol contracts
    - Calibrable: Pydantic-field annotation marking a calibrable parameter
    - discover_calibrable: auto-discover calibrable fields in a config tree
    - build_optimizer: adapter registry lookup
"""

from hydromodpy.calibration.config import (
    CalibObjectiveBlockDecl,
    CalibOutputDecl,
    CalibParameterDecl,
    CalibrationConfig,
)
from hydromodpy.calibration.engine import CalibrationEngine, CalibrationSession
from hydromodpy.calibration.materialize import materialize_candidate
from hydromodpy.calibration.objective import (
    CompositeObjective,
    ConfigBlockObjective,
    Objective,
    ObjectiveValue,
    ObservationSet,
    ScalarObjective,
    SimulationOutput,
    build_objective_from_config,
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
    apply_parameter_to_config,
    discover_calibrable,
)
from hydromodpy.calibration.report import CalibrationReport

__all__ = [
    "CalibrationEngine",
    "CalibrationSession",
    "CalibrationReport",
    "CalibrationConfig",
    "CalibParameterDecl",
    "CalibOutputDecl",
    "CalibObjectiveBlockDecl",
    "Optimizer",
    "Objective",
    "ObjectiveValue",
    "ObservationSet",
    "SimulationOutput",
    "ScalarObjective",
    "CompositeObjective",
    "ConfigBlockObjective",
    "build_objective_from_config",
    "Calibrable",
    "CalibParameter",
    "ParameterSpace",
    "apply_parameter_to_config",
    "ParamSuggestion",
    "EvaluationResult",
    "build_optimizer",
    "register_optimizer",
    "discover_calibrable",
    "materialize_candidate",
]
