"""Input paths and labels for catchment reports."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from hydromodpy.display.catchment_report.settings import CatchmentReportSettings


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
    observed_discharge_path: Path | None = None
    observed_discharge_station_id: str | None = None
    preset_name: str | None = None
    pipeline_run_overview: bool = False
    pipeline_run_simulation: bool = False
    pipeline_build_context_artifacts: bool = True
    pipeline_build_report_html: bool = True
    pipeline_no_lock: bool = True
    pipeline_stream_run_logs: bool = False
    pipeline_strict_figure_postflight: bool = False

    @classmethod
    def from_toml(cls, path: Path) -> CatchmentReportInputs:
        return cls.from_settings(CatchmentReportSettings.from_toml(path))

    @classmethod
    def from_settings(
        cls,
        settings: CatchmentReportSettings,
    ) -> CatchmentReportInputs:
        observed = settings.observed_discharge
        return cls.from_project_layout(
            output_dir=settings.report.output_dir,
            site_label=settings.report.site_label,
            station_label=settings.report.station_label,
            title=settings.report.title,
            preset_name=settings.report.preset_name,
            watershed_project_dir=settings.layout.watershed_project_dir,
            context_outputs_dir=settings.layout.context_outputs_dir,
            data_overview_project_dir=settings.layout.data_overview_project_dir,
            simulation_workspace_dir=settings.layout.simulation_workspace_dir,
            simulation_name=settings.layout.simulation_name,
            context_summary_name=settings.layout.context_summary_name,
            transient_config_name=settings.layout.transient_config_name,
            overview_config_name=settings.layout.overview_config_name,
            observed_discharge_path=observed.path if observed else None,
            observed_discharge_station_id=observed.station_id if observed else None,
            pipeline_run_overview=settings.pipeline.run_overview,
            pipeline_run_simulation=settings.pipeline.run_simulation,
            pipeline_build_context_artifacts=settings.pipeline.build_context_artifacts,
            pipeline_build_report_html=settings.pipeline.build_report_html,
            pipeline_no_lock=settings.pipeline.no_lock,
            pipeline_stream_run_logs=settings.pipeline.stream_run_logs,
            pipeline_strict_figure_postflight=settings.pipeline.strict_figure_postflight,
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
        context_summary_name: str | None = None,
        transient_config_name: str | None = None,
        overview_config_name: str | None = None,
        observed_discharge_path: Path | None = None,
        observed_discharge_station_id: str | None = None,
        preset_name: str | None = None,
        pipeline_run_overview: bool = False,
        pipeline_run_simulation: bool = False,
        pipeline_build_context_artifacts: bool = True,
        pipeline_build_report_html: bool = True,
        pipeline_no_lock: bool = True,
        pipeline_stream_run_logs: bool = False,
        pipeline_strict_figure_postflight: bool = False,
    ) -> CatchmentReportInputs:
        data_overview_project_dir = data_overview_project_dir or watershed_project_dir
        simulation_workspace_dir = simulation_workspace_dir or watershed_project_dir
        context_summary_name = context_summary_name or _context_summary_name(
            context_outputs_dir,
            site_label,
        )
        transient_config_name = transient_config_name or f"run_{simulation_name}.toml"
        overview_config_name = overview_config_name or "config_overview.toml"
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
            overview_figures=data_overview_project_dir / "figures" / "overview",
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
            overview_standard_html=(
                data_overview_project_dir / "web_review" / "standard" / "index.html"
            ),
            transient_config=(watershed_project_dir / transient_config_name).resolve(),
            overview_config=(data_overview_project_dir / overview_config_name).resolve(),
            title=title,
            observed_discharge_path=observed_discharge_path,
            observed_discharge_station_id=observed_discharge_station_id,
            preset_name=preset_name,
            pipeline_run_overview=pipeline_run_overview,
            pipeline_run_simulation=pipeline_run_simulation,
            pipeline_build_context_artifacts=pipeline_build_context_artifacts,
            pipeline_build_report_html=pipeline_build_report_html,
            pipeline_no_lock=pipeline_no_lock,
            pipeline_stream_run_logs=pipeline_stream_run_logs,
            pipeline_strict_figure_postflight=pipeline_strict_figure_postflight,
        )


def _context_summary_name(context_outputs_dir: Path, site_label: str) -> str:
    candidates = sorted((context_outputs_dir / "context").glob("*_gauged_context_summary.json"))
    if len(candidates) == 1:
        return candidates[0].name
    return f"{_slug(site_label)}_gauged_context_summary.json"


def _slug(value: str) -> str:
    cleaned = "".join(char.lower() if char.isalnum() else "_" for char in value)
    parts = [part for part in cleaned.split("_") if part]
    return "_".join(parts)


__all__ = ["CatchmentReportInputs"]
