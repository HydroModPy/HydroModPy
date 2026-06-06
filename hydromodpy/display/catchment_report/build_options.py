"""Execution options for the catchment report pipeline."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hydromodpy.core.toml_io.loader import load_toml_with_base_config
from hydromodpy.display.catchment_report.settings import CATCHMENT_REPORT_PROFILE
from hydromodpy.display.report_artifacts import HtmlReportIntent


@dataclass(frozen=True)
class CatchmentReportBuildOptions:
    """Options controlling report artifact production.

    These values are execution policy, not report layout. They are loaded from
    CLI overrides first and, when present, from ``[pipeline]`` sections in
    older report TOMLs.
    """

    run_overview: bool = False
    run_simulation: bool = False
    build_context_artifacts: bool = True
    build_report_html: bool = True
    no_lock: bool = True
    stream_run_logs: bool = False
    strict_figure_postflight: bool = False

    @classmethod
    def from_toml(cls, path: Path) -> CatchmentReportBuildOptions:
        config_path = Path(path).expanduser().resolve()
        return cls.from_mapping(load_toml_with_base_config(config_path))

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> CatchmentReportBuildOptions:
        pipeline = payload.get("pipeline", {})
        report = payload.get("report", {})
        html_report = HtmlReportIntent.from_mapping(
            report.get("html") if isinstance(report, Mapping) else None,
            default_profile=CATCHMENT_REPORT_PROFILE,
        )
        html_section_present = html_report.enabled or html_report.build_at_end
        build_report_default = html_report.build_at_end if html_section_present else True
        strict_default = html_report.strict if html_section_present else False

        return cls(
            run_overview=_optional_bool_with_default(pipeline, "run_overview", False),
            run_simulation=_optional_bool_with_default(pipeline, "run_simulation", False),
            build_context_artifacts=_optional_bool_with_default(
                pipeline,
                "build_context_artifacts",
                True,
            ),
            build_report_html=_optional_bool_with_default(
                pipeline,
                "build_report_html",
                build_report_default,
            ),
            no_lock=_optional_bool_with_default(pipeline, "no_lock", True),
            stream_run_logs=_optional_bool_with_default(pipeline, "stream_run_logs", False),
            strict_figure_postflight=_optional_bool_with_default(
                pipeline,
                "strict_figure_postflight",
                strict_default,
            ),
        )

    def with_overrides(
        self,
        *,
        run_overview: bool | None = None,
        run_simulation: bool | None = None,
        build_context_artifacts: bool | None = None,
        build_report_html: bool | None = None,
        no_lock: bool | None = None,
        stream_run_logs: bool | None = None,
        strict_figure_postflight: bool | None = None,
    ) -> CatchmentReportBuildOptions:
        return type(self)(
            run_overview=_override_or_default(run_overview, self.run_overview),
            run_simulation=_override_or_default(run_simulation, self.run_simulation),
            build_context_artifacts=_override_or_default(
                build_context_artifacts,
                self.build_context_artifacts,
            ),
            build_report_html=_override_or_default(
                build_report_html,
                self.build_report_html,
            ),
            no_lock=_override_or_default(no_lock, self.no_lock),
            stream_run_logs=_override_or_default(stream_run_logs, self.stream_run_logs),
            strict_figure_postflight=_override_or_default(
                strict_figure_postflight,
                self.strict_figure_postflight,
            ),
        )


def _optional_bool_with_default(payload: Any, key: str, default: bool) -> bool:
    if not isinstance(payload, Mapping):
        return default
    value = payload.get(key)
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    raise ValueError(f"Catchment report build option {key!r} must be a boolean.")


def _override_or_default(value: bool | None, default: bool) -> bool:
    return default if value is None else value


__all__ = ["CatchmentReportBuildOptions"]
