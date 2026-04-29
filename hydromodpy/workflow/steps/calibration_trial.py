"""Workflow-side concrete provider for the calibration trial primitive.

The :mod:`hydromodpy.calibration.runners.trial` module consumes a
``TrialPipelineProvider`` Protocol so the calibration package never imports
the workflow package directly. This module ships the canonical
implementation, backed by :class:`hydromodpy.workflow.runner.Pipeline`,
:func:`hydromodpy.workflow.orchestrator.standard_steps`, and the support /
data-binder helpers wired into the workflow steps.

The bootstrap (see :func:`hydromodpy._bootstrap.bootstrap`) instantiates
the provider once and registers it via
``register_trial_pipeline_provider``.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from hydromodpy.calibration.runners.contracts import (
    TrialPipelineProvider,
    TrialPipelineRunner,
    TrialStep,
    register_trial_pipeline_provider,
)
from hydromodpy.spatial.domain.spatial_support import (
    build_default_spatial_support_provider_registry,
)
from hydromodpy.workflow.internals.dependencies import earliest_affected_step
from hydromodpy.workflow.internals.state import PipelineState
from hydromodpy.workflow.orchestrator import standard_steps
from hydromodpy.workflow.runner import Pipeline
from hydromodpy.workflow.steps.data_loading import apply_structural_updates_from_data
from hydromodpy.workflow.steps.setup import (
    collect_requested_support_ids,
    resolve_support_configs,
)


@dataclass(frozen=True)
class WorkflowTrialPipelineProvider(TrialPipelineProvider):
    """Concrete ``TrialPipelineProvider`` backed by the workflow package."""

    def standard_steps(self) -> Sequence[TrialStep]:
        return standard_steps()

    def earliest_affected_step(
        self,
        override_paths: Iterable[str],
        steps: Sequence[TrialStep],
    ) -> int:
        return earliest_affected_step(override_paths, steps)

    def make_pipeline(self, steps: Sequence[TrialStep]) -> TrialPipelineRunner:
        return Pipeline(steps)

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
    register_trial_pipeline_provider(WorkflowTrialPipelineProvider())


__all__ = [
    "WorkflowTrialPipelineProvider",
    "register_default_trial_pipeline_provider",
]
