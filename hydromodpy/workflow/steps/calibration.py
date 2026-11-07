"""Calibration step - report rendering plus calibration trial provider."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hydromodpy.calibration.runners.contracts import (
    TrialPipelineProvider,
    TrialPipelineRunner,
    TrialStep,
    register_trial_pipeline_provider,
)
from hydromodpy.model.domain.spatial_support import (
    build_default_spatial_support_provider_registry,
    collect_requested_support_ids,
    resolve_support_configs,
)
from hydromodpy.workflow.runner import Pipeline
from hydromodpy.workflow.state import PipelineState
from hydromodpy.workflow.steps.data import apply_structural_updates_from_data
from hydromodpy.workflow.steps.dependencies import earliest_affected_step
from hydromodpy.workflow.steps.run_solver import RunSolverStep
from hydromodpy.workflow.steps.sequence import standard_steps

# ---------------------------------------------------------------------------
# Calibration report
# ---------------------------------------------------------------------------


def step_render_calibration_report(
    *,
    session_dir: Path,
    figure_names: list[str] | tuple[str, ...] | None = None,
) -> Path:
    """Load one calibration session from its directory and render its HTML report.

    Returns ``sessions/<session>/report/index.html``; the figures land in
    ``sessions/<session>/figures/``. Figures that fail to render are skipped
    with a warning so the report always produces output even on partial data.
    """
    from hydromodpy.calibration.report import load_session_report_data
    from hydromodpy.display.calibration_report import render_session

    session_data = load_session_report_data(Path(session_dir))
    written = render_session(
        session_data,
        figure_names=figure_names,
        session_dir=Path(session_dir),
    )
    return written[-1]


# ---------------------------------------------------------------------------
# Calibration trial pipeline provider
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _WorkflowTrialPipelineProvider(TrialPipelineProvider):
    """Concrete ``TrialPipelineProvider`` backed by the workflow package."""

    def standard_steps(self) -> Sequence[TrialStep]:
        return standard_steps()

    def earliest_affected_step(
        self,
        override_paths: Iterable[str],
        steps: Sequence[TrialStep],
    ) -> int:
        return earliest_affected_step(override_paths, steps)

    def make_pipeline(
        self, steps: Sequence[TrialStep], *, run_dir: Path | None = None
    ) -> TrialPipelineRunner:
        return Pipeline(steps, run_dir=run_dir)

    def with_solver_launcher(
        self,
        steps: Sequence[TrialStep],
        launcher: Any,
    ) -> tuple[TrialStep, ...]:
        return tuple(
            RunSolverStep(launcher=launcher) if step.name == RunSolverStep.name else step
            for step in steps
        )

    def make_state(self, run_id: str, data: Mapping[str, Any]) -> Any:
        return PipelineState(run_id=run_id, data=dict(data))

    def collect_requested_support_ids(self, flow_cfg: object) -> tuple[str, ...]:
        return collect_requested_support_ids(flow_cfg)

    def resolve_support_configs(
        self,
        domain_cfg: object,
        requested_support_ids: tuple[str, ...],
    ) -> dict[str, object]:
        return resolve_support_configs(domain_cfg, requested_support_ids)

    def build_default_spatial_support_provider_registry(self) -> object:
        return build_default_spatial_support_provider_registry()

    def apply_structural_updates_from_data(self, ctx: Any) -> None:
        apply_structural_updates_from_data(ctx)


def register_default_trial_pipeline_provider() -> None:
    """Register the workflow-backed provider for calibration trial primitives."""
    register_trial_pipeline_provider(_WorkflowTrialPipelineProvider())


__all__ = [
    "register_default_trial_pipeline_provider",
    "step_render_calibration_report",
]
