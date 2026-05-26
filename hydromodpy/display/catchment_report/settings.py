"""TOML-backed settings for catchment reports."""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class CatchmentReportSettings:
    report: ReportSettings
    layout: LayoutSettings
    observed_discharge: ObservedDischargeSettings | None
    pipeline: PipelineSettings

    @classmethod
    def from_toml(cls, path: Path) -> CatchmentReportSettings:
        config_path = Path(path).expanduser().resolve()
        payload = tomllib.loads(config_path.read_text(encoding="utf-8-sig"))
        return cls.from_mapping(payload, base_dir=config_path.parent)

    @classmethod
    def from_mapping(
        cls,
        payload: Mapping[str, Any],
        *,
        base_dir: Path,
    ) -> CatchmentReportSettings:
        report = _section(payload, "report")
        layout = _section(payload, "layout")
        context = payload.get("context", {})
        pipeline = payload.get("pipeline", {})

        return cls(
            report=ReportSettings.from_mapping(report, base_dir=base_dir),
            layout=LayoutSettings.from_mapping(layout, base_dir=base_dir),
            observed_discharge=ObservedDischargeSettings.from_context(
                context,
                base_dir=base_dir,
            ),
            pipeline=PipelineSettings.from_mapping(pipeline),
        )


@dataclass(frozen=True)
class ReportSettings:
    output_dir: Path
    site_label: str
    station_label: str
    title: str = ""
    allow_gallery_fallbacks: bool | None = None
    preset_name: str | None = None

    @classmethod
    def from_mapping(
        cls,
        payload: Mapping[str, Any],
        *,
        base_dir: Path,
    ) -> ReportSettings:
        return cls(
            output_dir=_path(base_dir, _required(payload, "output_dir")),
            site_label=str(_required(payload, "site_label")),
            station_label=str(_required(payload, "station_label")),
            title=str(payload.get("title", "")),
            allow_gallery_fallbacks=_optional_bool(payload, "allow_gallery_fallbacks"),
            preset_name=_optional_string(payload, "preset"),
        )


@dataclass(frozen=True)
class LayoutSettings:
    watershed_project_dir: Path
    context_outputs_dir: Path
    data_overview_project_dir: Path
    simulation_workspace_dir: Path
    simulation_name: str = "transient_nwt"
    context_summary_name: str | None = None
    transient_config_name: str | None = None
    overview_config_name: str | None = None

    @classmethod
    def from_mapping(
        cls,
        payload: Mapping[str, Any],
        *,
        base_dir: Path,
    ) -> LayoutSettings:
        watershed_project_dir = _path(base_dir, _required(payload, "watershed_project_dir"))
        return cls(
            watershed_project_dir=watershed_project_dir,
            context_outputs_dir=_path(base_dir, _required(payload, "context_outputs_dir")),
            data_overview_project_dir=_optional_path(
                base_dir,
                payload,
                "data_overview_project_dir",
                default=watershed_project_dir,
            ),
            simulation_workspace_dir=_optional_path(
                base_dir,
                payload,
                "simulation_workspace_dir",
                default=watershed_project_dir,
            ),
            simulation_name=str(payload.get("simulation_name", "transient_nwt")),
            context_summary_name=_optional_string(payload, "context_summary_name"),
            transient_config_name=_optional_string(payload, "transient_config_name"),
            overview_config_name=_optional_string(payload, "overview_config_name"),
        )


@dataclass(frozen=True)
class ObservedDischargeSettings:
    path: Path
    station_id: str | None = None

    @classmethod
    def from_context(
        cls,
        payload: Any,
        *,
        base_dir: Path,
    ) -> ObservedDischargeSettings | None:
        if not isinstance(payload, Mapping):
            return None
        observed = payload.get("observed_discharge", {})
        if not isinstance(observed, Mapping):
            return None
        path = _optional_context_path(base_dir, observed, "path")
        if path is None:
            return None
        return cls(
            path=path,
            station_id=_optional_string(observed, "station_id"),
        )


@dataclass(frozen=True)
class PipelineSettings:
    run_overview: bool = False
    run_simulation: bool = False
    build_context_artifacts: bool = True
    build_report_html: bool = True
    no_lock: bool = True
    stream_run_logs: bool = False
    strict_figure_postflight: bool = False
    context_builder_command: tuple[str, ...] | None = None

    @classmethod
    def from_mapping(cls, payload: Any) -> PipelineSettings:
        return cls(
            run_overview=_optional_bool_with_default(payload, "run_overview", False),
            run_simulation=_optional_bool_with_default(payload, "run_simulation", False),
            build_context_artifacts=_optional_bool_with_default(
                payload,
                "build_context_artifacts",
                True,
            ),
            build_report_html=_optional_bool_with_default(
                payload,
                "build_report_html",
                True,
            ),
            no_lock=_optional_bool_with_default(payload, "no_lock", True),
            stream_run_logs=_optional_bool_with_default(payload, "stream_run_logs", False),
            strict_figure_postflight=_optional_bool_with_default(
                payload,
                "strict_figure_postflight",
                False,
            ),
            context_builder_command=_optional_string_tuple(
                payload,
                "context_builder_command",
            ),
        )


def _section(payload: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    value = payload.get(name)
    if not isinstance(value, Mapping):
        raise ValueError(f"Missing [{name}] section in catchment report config.")
    return value


def _required(payload: Mapping[str, Any], key: str) -> Any:
    try:
        return payload[key]
    except KeyError as exc:
        raise ValueError(f"Missing required catchment report config key: {key!r}.") from exc


def _optional_string(payload: Mapping[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    return str(value)


def _optional_bool(payload: Mapping[str, Any], key: str) -> bool | None:
    value = payload.get(key)
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    raise ValueError(f"Catchment report config key {key!r} must be a boolean.")


def _optional_bool_with_default(payload: Any, key: str, default: bool) -> bool:
    if not isinstance(payload, Mapping):
        return default
    value = payload.get(key)
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    raise ValueError(f"Catchment report config key {key!r} must be a boolean.")


def _optional_string_tuple(payload: Any, key: str) -> tuple[str, ...] | None:
    if not isinstance(payload, Mapping):
        return None
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, list) or not value:
        raise ValueError(
            f"Catchment report config key {key!r} must be a non-empty string array."
        )
    if not all(isinstance(item, str) for item in value):
        raise ValueError(
            f"Catchment report config key {key!r} must be a non-empty string array."
        )
    return tuple(value)


def _optional_path(
    base_dir: Path,
    payload: Mapping[str, Any],
    key: str,
    *,
    default: Path,
) -> Path:
    value = payload.get(key)
    if value is None:
        return default
    return _path(base_dir, value)


def _optional_context_path(
    base_dir: Path,
    payload: Any,
    key: str,
) -> Path | None:
    if not isinstance(payload, Mapping):
        return None
    value = payload.get(key)
    if value is None:
        return None
    return _path(base_dir, value)


def _path(base_dir: Path, value: Any) -> Path:
    path = Path(str(value)).expanduser()
    if not path.is_absolute():
        path = base_dir / path
    return path.resolve()


__all__ = [
    "CatchmentReportSettings",
    "LayoutSettings",
    "ObservedDischargeSettings",
    "PipelineSettings",
    "ReportSettings",
]
