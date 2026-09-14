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
    CalibOutputBoundary,
    CalibOutputCell,
    CalibOutputDecl,
    CalibOutputPoint,
    CalibParameterDecl,
    CalibrationConfig,
    validate_calib_output,
)
from hydromodpy.calibration.optim.engine import CalibrationEngine, CalibrationSession
from hydromodpy.calibration.optim.objective import (
    CompositeObjective,
    ConfigBlockObjective,
    Objective,
    ObjectiveValue,
    ObservationSet,
    ScalarObjective,
    SimulationOutput,
    build_objective_from_config,
)
from hydromodpy.calibration.optim.optimizer import (
    EvaluationResult,
    Optimizer,
    ParamSuggestion,
    available_optimizers,
    build_optimizer,
    register_optimizer,
)
from hydromodpy.calibration.optim.parameters import (
    CalibParameter,
    Calibrable,
    ParameterSpace,
    apply_parameter_to_config,
    discover_calibrable,
)
from hydromodpy.calibration.report import CalibrationReport
from hydromodpy.calibration.runners.materialize import materialize_candidate

__all__ = [
    "CalibrationEngine",
    "CalibrationSession",
    "CalibrationReport",
    "CalibrationConfig",
    "CalibParameterDecl",
    "CalibOutputDecl",
    "CalibOutputPoint",
    "CalibOutputBoundary",
    "CalibOutputCell",
    "CalibObjectiveBlockDecl",
    "validate_calib_output",
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
    "available_optimizers",
    "build_optimizer",
    "register_optimizer",
    "discover_calibrable",
    "materialize_candidate",
]
