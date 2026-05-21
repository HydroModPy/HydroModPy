"""Calibration step - report rendering plus calibration trial provider."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

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
from hydromodpy.workflow.steps.data import apply_structural_updates_from_data
from hydromodpy.workflow.steps.setup import (
    collect_requested_support_ids,
    resolve_support_configs,
)

if TYPE_CHECKING:
    from hydromodpy.results.catalog import SimulationCatalog


# ---------------------------------------------------------------------------
# Calibration report
# ---------------------------------------------------------------------------


def step_render_calibration_report(
    *,
    catalog: SimulationCatalog,
    session_id: str,
    workspace_root: Path,
    figure_names: list[str] | tuple[str, ...] | None = None,
    output_dir: Path | None = None,
) -> Path:
    """Load one calibration session and render its HTML report.

    Returns the path to the generated ``report.html``. Figures that
    fail to render are skipped with a warning so the report always
    produces output even on partial data.
    """
    from hydromodpy.calibration.report import load_session_report_data
    from hydromodpy.reporting.calibration_report import render_session

    session_data = load_session_report_data(
        catalog=catalog,
        session_id=session_id,
        workspace_root=workspace_root,
    )
    written = render_session(
        session_data,
        figure_names=figure_names,
        output_dir=output_dir,
    )
    return written[-1]


def step_render_network_transient_calibration_html(
    *,
    real_root: Path,
    web_root: Path | None = None,
    source_transient_config: Path | None = None,
    path_base: Path | None = None,
    page_title: str = "Diagnostic calibration reseau + debit transitoire",
    reference_run_root: Path | None = None,
    steady_summary_csv: Path | None = None,
    truth_packages: Iterable[Path] | None = None,
    score_tables: Iterable[Path] | None = None,
) -> Path:
    """Render the reusable network/transient calibration diagnostic HTML page."""

    from hydromodpy.calibration.reporting import build_network_transient_html
    from hydromodpy.calibration.reporting.network_transient_html import SOURCE_TRANSIENT_CONFIG

    return build_network_transient_html(
        real_root=real_root,
        web_root=web_root,
        source_transient_config=source_transient_config or SOURCE_TRANSIENT_CONFIG,
        path_base=path_base,
        page_title=page_title,
        reference_run_root=reference_run_root,
        steady_summary_csv=steady_summary_csv,
        truth_packages=truth_packages,
        score_tables=score_tables,
    )


# ---------------------------------------------------------------------------
# Calibration trial pipeline provider
# ---------------------------------------------------------------------------


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

    def resolve_mesh_runtime_sections(
        self,
        raw_toml: Mapping[str, Any],
        config_path: str | Path,
    ) -> dict[str, Any]:
        from hydromodpy.workflow.steps.mesh import (
            resolve_optional_mesh_input,
            resolve_optional_mesh_section,
        )

        mesh_section_data = resolve_optional_mesh_section(raw_toml)
        constraints_mode = (
            None if mesh_section_data is None else str(mesh_section_data.constraints_mode)
        )
        return {
            "mesh_section_data": mesh_section_data,
            "constraints_mode": constraints_mode,
            "external_mesh_input": resolve_optional_mesh_input(raw_toml, config_path),
        }

    def apply_structural_updates_from_data(self, ctx: Any) -> None:
        apply_structural_updates_from_data(ctx)


def register_default_trial_pipeline_provider() -> None:
    """Register the workflow-backed provider for calibration trial primitives."""
    register_trial_pipeline_provider(WorkflowTrialPipelineProvider())


__all__ = [
    "WorkflowTrialPipelineProvider",
    "register_default_trial_pipeline_provider",
    "step_render_calibration_report",
    "step_render_network_transient_calibration_html",
]
