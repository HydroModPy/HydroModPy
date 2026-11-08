"""Helpers shared by the calibration tests."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hydromodpy.calibration.config import validate_calib_output
from hydromodpy.calibration.metrics.observable_scoring import StationBlockScorer
from hydromodpy.calibration.metrics.series import ObservedSeries
from hydromodpy.calibration.optim.optimizer import EvaluationResult
from hydromodpy.calibration.optim.parameters import CalibParameter, ParameterSpace
from hydromodpy.calibration.report import CalibrationReport
from hydromodpy.core.contracts.observables import ObservableResult
from hydromodpy.model.flow_config import FlowConfig


class _Project:
    def __init__(self, flow: FlowConfig) -> None:
        self.flow = flow


@dataclass
class Setup:
    workspace: Any = None
    geographic: Any = None
    flow: Any = None
    transport: Any = None
    slot_request: Any = None
    run_id: str = "toy"
    time_grid: Any = None


def one_state(mapped, time: str = "last"):  # noqa: F811
    return validate_calib_output(
        {
            "support": "network",
            "map": {"complete": str(mapped)},
            "model": {"neighbours": "D8", "seepage_threshold": 0.0},
            "time": time,
        }
    )


def _score(observed, simulated, metric: str, *, variable: str = "discharge", **options):
    """Score two series as ``variable`` + ``objective`` does: through one implicit block."""
    scorer = StationBlockScorer(
        variable, metric, [ObservedSeries("S", variable, observed)], **options
    )
    answer = ObservableResult("S", simulated.to_numpy(), "-", simulated.index)
    return scorer.score({"S": answer})


def two_dim_space() -> ParameterSpace:
    return ParameterSpace(
        [
            CalibParameter(name="x", lower=0.0, upper=1.0),
            CalibParameter(name="y", lower=-2.0, upper=2.0),
        ]
    )


def unit_space() -> ParameterSpace:
    return ParameterSpace([CalibParameter(name="x", lower=0.0, upper=1.0)])
