"""Final optional HTML report step."""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

from hydromodpy.core.exceptions import ConfigError
from hydromodpy.core.logging import get_logger
from hydromodpy.display.report_artifacts import (
    REPORT_ARTIFACT_MANIFEST_SCHEMA,
    load_report_artifact_manifest,
    missing_required_artifact_ids,
)
from hydromodpy.display.report_profiles import (
    report_html_is_enabled,
    report_html_is_strict,
    report_profile_name,
)
from hydromodpy.workflow.internals.state import ExportedState, PipelineState

logger = get_logger(__name__)


class HtmlReportStep:
    """Build the optional HTML report after simulation display artifacts exist."""

    name = "html_report"
    tin: ClassVar[type] = ExportedState
    tout: ClassVar[type] = ExportedState
    config_sections: ClassVar[tuple[str, ...]] = ("report",)

    def depends_on(self) -> tuple[str, ...]:
        return ("display",)

    def rebuild_state(
        self,
        *,
        prior_state: PipelineState,
        workspace: Path,
        run_id: str,
    ) -> PipelineState:
        del workspace, run_id
        ctx = prior_state.get("ctx")
        html_report = _expected_html_path(ctx)
        postflight = _expected_postflight_path(ctx)
        return prior_state.advance(
            step_index=prior_state.step_index + 1,
            step_name=self.name,
            ctx=ctx,
            html_report=html_report if html_report and html_report.exists() else None,
            html_report_postflight=postflight if postflight and postflight.exists() else None,
            html_report_source_manifest=state_source_manifest(prior_state),
            html_report_error=None,
        )

    def run(self, state: PipelineState) -> PipelineState:
        ctx = state.get("ctx")
        report_cfg = getattr(getattr(ctx, "cfg", None), "report", None)
        html_cfg = getattr(report_cfg, "html", None)
        html_report = None
        postflight = None
        source_manifest = None
        error = None

        if not report_html_is_enabled(report_cfg) or not getattr(
            html_cfg,
            "build_at_end",
            False,
        ):
            return state.advance(
                step_index=state.step_index + 1,
                step_name=self.name,
                ctx=ctx,
                html_report=None,
                html_report_postflight=None,
                html_report_error=None,
            )

        try:
            html_report, postflight, source_manifest = _build_html_report(
                report_cfg,
                state=state,
                ctx=ctx,
            )
        except Exception as exc:
            error = str(exc)
            if report_html_is_strict(report_cfg):
                raise
            logger.warning("Optional HTML report failed: %s", exc)

        return state.advance(
            step_index=state.step_index + 1,
            step_name=self.name,
            ctx=ctx,
            html_report=html_report,
            html_report_postflight=postflight,
            html_report_source_manifest=source_manifest,
            html_report_error=error,
        )


def _build_html_report(
    report_cfg: object,
    *,
    state: PipelineState,
    ctx: object,
) -> tuple[Path | None, Path | None, Path | None]:
    profile = report_profile_name(report_cfg)
    html_cfg = getattr(report_cfg, "html", None)
    config_path = getattr(html_cfg, "config_path", None)
    if profile != "catchment_gauged":
        raise ConfigError(f"HTML report profile {profile!r} is not implemented for simulations.")
    if config_path is None:
        raise ConfigError(
            "[report.html].config_path is required to build a catchment_gauged HTML "
            "report at the end of a simulation."
        )
    source_manifest = state_source_manifest(state)
    if source_manifest is not None:
        _validate_source_manifest(source_manifest, expected_profile=profile)
    elif report_html_is_strict(report_cfg):
        raise ConfigError(
            "A report display artifact manifest is required when "
            "[report.html].strict = true."
        )

    from hydromodpy.display.catchment_report.pipeline import run_catchment_report_pipeline

    result = run_catchment_report_pipeline(
        Path(config_path),
        run_overview=False,
        run_simulation=False,
        build_context_artifacts=True,
        build_report_html=True,
        strict_figure_postflight=report_html_is_strict(report_cfg),
        source_artifact_manifest=source_manifest,
        simulation_config_path=_current_config_path(ctx),
    )
    return result.html_report, result.postflight_report, source_manifest


def state_source_manifest(state: PipelineState) -> Path | None:
    value = state.get("report_display_manifest")
    if value in (None, ""):
        return None
    path = Path(value)
    return path if path.exists() else None


def _validate_source_manifest(path: Path, *, expected_profile: str) -> None:
    payload = load_report_artifact_manifest(path)
    schema = payload.get("schema_version")
    if schema != REPORT_ARTIFACT_MANIFEST_SCHEMA:
        raise ConfigError(
            "Unsupported report display artifact manifest schema "
            f"{schema!r}; expected {REPORT_ARTIFACT_MANIFEST_SCHEMA!r}."
        )
    profile = str(payload.get("profile", ""))
    if profile and profile != expected_profile:
        raise ConfigError(
            f"Report display artifact manifest profile {profile!r} does not match "
            f"requested profile {expected_profile!r}."
        )
    missing = missing_required_artifact_ids(payload)
    if missing:
        details = ", ".join(missing)
        raise ConfigError(
            "Report display artifact manifest has missing required artifacts: "
            f"{details}"
        )


def _expected_html_path(ctx: object) -> Path | None:
    config_path = _report_config_path(ctx)
    if config_path is None:
        return None
    try:
        from hydromodpy.display.catchment_report.inputs import CatchmentReportInputs

        inputs = CatchmentReportInputs.from_toml(config_path)
    except Exception:
        return None
    return inputs.output_dir / "web" / "index.html"


def _expected_postflight_path(ctx: object) -> Path | None:
    config_path = _report_config_path(ctx)
    if config_path is None:
        return None
    try:
        from hydromodpy.display.catchment_report.inputs import CatchmentReportInputs

        inputs = CatchmentReportInputs.from_toml(config_path)
    except Exception:
        return None
    return inputs.output_dir / "block_report_postflight.json"


def _report_config_path(ctx: object) -> Path | None:
    report_cfg = getattr(getattr(ctx, "cfg", None), "report", None)
    html_cfg = getattr(report_cfg, "html", None)
    config_path = getattr(html_cfg, "config_path", None)
    return None if config_path is None else Path(config_path)


def _current_config_path(ctx: object) -> Path | None:
    config_path = getattr(ctx, "config_path", None)
    return None if config_path is None else Path(config_path)


__all__ = ["HtmlReportStep"]
