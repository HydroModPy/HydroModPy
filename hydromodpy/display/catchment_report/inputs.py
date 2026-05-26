"""Input paths and labels for catchment reports."""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class CatchmentReportInputs:
    output_dir: Path
    site_label: str
    station_label: str
    watershed_project_dir: Path
    context_outputs_dir: Path
    data_overview_project_dir: Path
    simulation_workspace_dir: Path
    simulation_name: str
    context_summary: Path
    context_assets: Path
    overview_figures: Path
    data_overview_figures: Path
    simulation_figures: Path
    simulation_export: Path
    geographic_scratch: Path
    generated_network_root: Path
    context_html: Path
    overview_standard_html: Path
    transient_config: Path
    overview_config: Path
    title: str = ""
    allow_gallery_fallbacks: bool | None = None
    observed_discharge_path: Path | None = None
    observed_discharge_station_id: str | None = None

    @classmethod
    def from_toml(cls, path: Path) -> CatchmentReportInputs:
        config_path = Path(path).expanduser().resolve()
        payload = tomllib.loads(config_path.read_text(encoding="utf-8-sig"))
        base_dir = config_path.parent
        report = _section(payload, "report")
        layout = _section(payload, "layout")
        context = payload.get("context", {})
        observed = context.get("observed_discharge", {}) if isinstance(context, Mapping) else {}
        watershed_project_dir = _path(base_dir, _required(layout, "watershed_project_dir"))
        data_overview_project_dir = _optional_path(
            base_dir,
            layout,
            "data_overview_project_dir",
            default=watershed_project_dir,
        )
        simulation_workspace_dir = _optional_path(
            base_dir,
            layout,
            "simulation_workspace_dir",
            default=watershed_project_dir,
        )
        return cls.from_project_layout(
            output_dir=_path(base_dir, _required(report, "output_dir")),
            site_label=str(_required(report, "site_label")),
            station_label=str(_required(report, "station_label")),
            title=str(report.get("title", "")),
            allow_gallery_fallbacks=_optional_bool(report, "allow_gallery_fallbacks"),
            watershed_project_dir=watershed_project_dir,
            context_outputs_dir=_path(base_dir, _required(layout, "context_outputs_dir")),
            data_overview_project_dir=data_overview_project_dir,
            simulation_workspace_dir=simulation_workspace_dir,
            simulation_name=str(layout.get("simulation_name", "transient_nwt")),
            context_summary_name=_optional_string(layout, "context_summary_name"),
            transient_config_name=_optional_string(layout, "transient_config_name"),
            overview_config_name=str(layout.get("overview_config_name", "config_overview.toml")),
            observed_discharge_path=_optional_context_path(base_dir, observed, "path"),
            observed_discharge_station_id=_optional_string(observed, "station_id"),
        )

    @classmethod
    def from_project_layout(
        cls,
        *,
        output_dir: Path,
        site_label: str,
        station_label: str,
        watershed_project_dir: Path,
        context_outputs_dir: Path,
        data_overview_project_dir: Path | None = None,
        simulation_workspace_dir: Path | None = None,
        simulation_name: str = "transient_nwt",
        title: str = "",
        allow_gallery_fallbacks: bool | None = None,
        context_summary_name: str | None = None,
        transient_config_name: str | None = None,
        overview_config_name: str = "config_overview.toml",
        observed_discharge_path: Path | None = None,
        observed_discharge_station_id: str | None = None,
    ) -> CatchmentReportInputs:
        data_overview_project_dir = data_overview_project_dir or watershed_project_dir
        simulation_workspace_dir = simulation_workspace_dir or watershed_project_dir
        context_summary_name = context_summary_name or _context_summary_name(
            context_outputs_dir,
            site_label,
        )
        transient_config_name = transient_config_name or f"run_{simulation_name}.toml"
        return cls(
            output_dir=output_dir,
            site_label=site_label,
            station_label=station_label,
            watershed_project_dir=watershed_project_dir,
            context_outputs_dir=context_outputs_dir,
            data_overview_project_dir=data_overview_project_dir,
            simulation_workspace_dir=simulation_workspace_dir,
            simulation_name=simulation_name,
            context_summary=context_outputs_dir / "context" / context_summary_name,
            context_assets=context_outputs_dir / "web" / "assets",
            overview_figures=watershed_project_dir / "figures" / "overview",
            data_overview_figures=data_overview_project_dir / "figures" / "overview",
            simulation_figures=simulation_workspace_dir / "figures" / simulation_name,
            simulation_export=(
                simulation_workspace_dir / "exports" / simulation_name / "timeseries.csv"
            ),
            geographic_scratch=(
                simulation_workspace_dir / ".solver_scratch" / "_preprocessing" / "geographic"
            ),
            generated_network_root=simulation_workspace_dir / "simulations",
            context_html=context_outputs_dir / "web" / "index.html",
            overview_standard_html=watershed_project_dir / "web_review" / "standard" / "index.html",
            transient_config=watershed_project_dir / transient_config_name,
            overview_config=data_overview_project_dir / overview_config_name,
            title=title,
            allow_gallery_fallbacks=allow_gallery_fallbacks,
            observed_discharge_path=observed_discharge_path,
            observed_discharge_station_id=observed_discharge_station_id,
        )


def _context_summary_name(context_outputs_dir: Path, site_label: str) -> str:
    candidates = sorted((context_outputs_dir / "context").glob("*_gauged_context_summary.json"))
    if len(candidates) == 1:
        return candidates[0].name
    return f"{_slug(site_label)}_gauged_context_summary.json"


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


def _slug(value: str) -> str:
    cleaned = "".join(char.lower() if char.isalnum() else "_" for char in value)
    parts = [part for part in cleaned.split("_") if part]
    return "_".join(parts)


__all__ = ["CatchmentReportInputs"]
