"""Trial pipeline implementation backed by the project and workflow packages.

Calibration cannot import the workflow or project package directly (layer-matrix
rule). It defines a :class:`~hydromodpy.calibration.runners.trial.TrialPipeline`
Protocol that bundles the workflow steps, runners, state construction, and
configuration loaders.

This module implements that contract in :class:`WorkflowTrialPipeline` and
registers it through :func:`fill_trial_pipeline`. Heavy dependencies are
imported inside method bodies so filling the pipeline only imports the trial
primitives.

One global crosses to a lower layer: the trial pipeline of
``calibration/runners/trial.py``, filled here by ``fill_trial_pipeline``. No other
adapter is wired through a global. Each entry of ``calibrate.py`` that reads the
pipeline fills it first, and so do the calibration adapter of ``dispatch/workflow.py``,
``rerun_config`` and the check of ``check_source.py``. The command line fills nothing.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from hydromodpy.calibration.runners.trial import (
    TrialPipelineRunner,
    TrialStep,
    install_trial_pipeline,
)

if TYPE_CHECKING:
    from pydantic import BaseModel


@dataclass(frozen=True)
class WorkflowTrialPipeline:
    """Concrete :class:`TrialPipeline` backed by workflow and project."""

    def standard_steps(self) -> Sequence[TrialStep]:
        from hydromodpy.workflow.steps.sequence import standard_steps

        return standard_steps()

    def earliest_affected_step(
        self,
        override_paths: Iterable[str],
        steps: Sequence[TrialStep],
    ) -> int:
        from hydromodpy.workflow.steps.dependencies import earliest_affected_step

        return earliest_affected_step(override_paths, steps)

    def make_pipeline(
        self,
        steps: Sequence[TrialStep],
        *,
        run_dir: Path | None = None,
    ) -> TrialPipelineRunner:
        from hydromodpy.workflow.runner import Pipeline

        return Pipeline(steps, run_dir=run_dir)

    def with_solver_launcher(
        self,
        steps: Sequence[TrialStep],
        launcher: Any,
    ) -> tuple[TrialStep, ...]:
        from hydromodpy.workflow.steps.run_solver import RunSolverStep

        return tuple(
            RunSolverStep(launcher=launcher) if step.name == RunSolverStep.name else step
            for step in steps
        )

    def make_state(self, run_id: str, data: Mapping[str, Any]) -> Any:
        from hydromodpy.workflow.state import PipelineState

        return PipelineState(run_id=run_id, data=dict(data))

    def apply_structural_updates_from_data(self, ctx: Any) -> None:
        from hydromodpy.workflow.steps.data import apply_structural_updates_from_data

        apply_structural_updates_from_data(ctx)

    def load_config(self, path: Path | str) -> BaseModel:
        from hydromodpy.config.loading import load

        return load(Path(path))

    def load_document(self, path: Path | str) -> dict[str, Any]:
        from hydromodpy.config.hydromodpy_config import ROOT_CONFIG
        from hydromodpy.config.loading import read_document

        return read_document(path, root=ROOT_CONFIG)

    def session_key(self, cfg: BaseModel) -> str | None:
        from hydromodpy.config.hydromodpy_config import HydroModPyConfig
        from hydromodpy.workflow.solution_key import session_solution_key

        # An evaluator that runs no HydroModPy model has no key: its document is hashed.
        if not isinstance(cfg, HydroModPyConfig):
            return None
        return session_solution_key(cfg)


def fill_trial_pipeline() -> None:
    """Register the production trial pipeline backed by project and workflow."""
    install_trial_pipeline(
        WorkflowTrialPipeline(),
        initializer=f"{__name__}:fill_trial_pipeline",
    )


__all__ = ["WorkflowTrialPipeline", "fill_trial_pipeline"]
