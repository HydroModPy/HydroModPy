"""TOML-backed settings for catchment reports."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hydromodpy.core.toml_io.loader import load_toml_with_base_config
from hydromodpy.display.report_artifacts import HtmlReportIntent

CATCHMENT_REPORT_PROFILE = "catchment_gauged"


@dataclass(frozen=True)
class CatchmentReportSettings:
    report: ReportSettings
    layout: LayoutSettings
    observed_discharge: ObservedDischargeSettings | None
    html_report: HtmlReportIntent

    @classmethod
    def from_toml(cls, path: Path) -> CatchmentReportSettings:
        config_path = Path(path).expanduser().resolve()
        payload = load_toml_with_base_config(config_path)
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
        html_report = HtmlReportIntent.from_mapping(
            report.get("html"),
            default_profile=CATCHMENT_REPORT_PROFILE,
        )

        return cls(
            report=ReportSettings.from_mapping(report, base_dir=base_dir),
            layout=LayoutSettings.from_mapping(layout, base_dir=base_dir),
            observed_discharge=ObservedDischargeSettings.from_context(
                context,
                base_dir=base_dir,
            ),
            html_report=html_report,
        )


@dataclass(frozen=True)
class ReportSettings:
    output_dir: Path
    site_label: str
    station_label: str
    title: str = ""
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
    "CATCHMENT_REPORT_PROFILE",
    "LayoutSettings",
    "ObservedDischargeSettings",
    "ReportSettings",
]
