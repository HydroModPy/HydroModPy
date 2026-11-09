"""Input paths and labels for catchment reports.

A catchment report describes one run and is written into it:
``runs/<simulation_name>/report/index.html``, its review pages under
``report/review/``, the figures it gathers under ``report/figures/`` and its
context files under ``report/context/``. Every path follows the run name, so
pointing the report at another version of the run moves all of them.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING

from hydromodpy.core.state.layout import runs_dir_for
from hydromodpy.core.state.scratch import kept_preprocessing_dir, preprocessing_dir
from hydromodpy.core.workspace import WorkspaceConfig
from hydromodpy.display.catchment_report.settings import CatchmentReportSettings
from hydromodpy.display.overview.location import (
    REVIEW_DIRNAME,
    overview_figures_dir,
    overview_name_of_file,
    overview_run_dir,
)
from hydromodpy.results.storage.contract import RUN_FIGURES_DIRNAME, RUN_REPORT_DIRNAME

if TYPE_CHECKING:
    from hydromodpy.core.config_kit.root import RootConfig

CONTEXT_DIRNAME = "context"
"""Folder of ``report/`` holding the context summary, its series and its page."""


@dataclass(frozen=True)
class CatchmentReportInputs:
    site_label: str
    station_label: str
    watershed_project_dir: Path
    data_overview_project_dir: Path
    simulation_workspace_dir: Path
    simulation_name: str
    context_summary_name: str
    geographic_scratch: Path
    generated_network_root: Path
    transient_config: Path
    overview_config: Path
    title: str = ""
    observed_discharge_path: Path | None = None
    observed_discharge_station_id: str | None = None
    geology_path: Path | None = None
    preset_name: str | None = None
    pipeline_run_overview: bool = False
    pipeline_run_simulation: bool = False
    pipeline_build_context_artifacts: bool = True
    pipeline_build_report_html: bool = True
    pipeline_stream_run_logs: bool = False
    pipeline_strict_figure_postflight: bool = False
    root: RootConfig | None = None

    @property
    def run_dir(self) -> Path:
        """``runs/<simulation_name>/``: the run the report describes and is written into."""
        return runs_dir_for(self.simulation_workspace_dir) / str(self.simulation_name)

    @property
    def data_dir(self) -> Path:
        """The data folder of the run: ``<workspace>/data``, or ``data/`` of a project alone."""
        return WorkspaceConfig(project_root=self.simulation_workspace_dir).data_path

    @property
    def output_dir(self) -> Path:
        """``report/`` of the run: the folder of the report."""
        return self.run_dir / RUN_REPORT_DIRNAME

    @property
    def simulation_figures(self) -> Path:
        """``figures/`` of the run: the figures the run rendered."""
        return self.run_dir / RUN_FIGURES_DIRNAME

    @property
    def context_dir(self) -> Path:
        """``report/context/`` of the run: the context summary and its series."""
        return self.output_dir / CONTEXT_DIRNAME

    @property
    def context_summary(self) -> Path:
        """The context summary JSON the report page is built from."""
        return self.context_dir / self.context_summary_name

    @property
    def context_assets(self) -> Path:
        """The images of the context page."""
        return self.context_dir / "web" / "assets"

    @property
    def context_html(self) -> Path:
        """The context page."""
        return self.context_dir / "web" / "index.html"

    @property
    def overview_dir(self) -> Path:
        """``runs/<overview>/`` of the data-overview project, named by its configuration."""
        return overview_run_dir(
            self.data_overview_project_dir,
            overview_name_of_file(self.overview_config, root=self.root),
        )

    @property
    def overview_figures(self) -> Path:
        """The panels the overview drew."""
        return overview_figures_dir(self.overview_dir)

    @property
    def data_overview_figures(self) -> Path:
        """The panels of the data overview: the same folder as :attr:`overview_figures`."""
        return self.overview_figures

    @property
    def overview_standard_html(self) -> Path:
        """The standard review page of the overview."""
        return self.overview_dir / RUN_REPORT_DIRNAME / REVIEW_DIRNAME / "standard" / "index.html"

    def with_simulation_name(self, name: str) -> CatchmentReportInputs:
        """Point the report at another run of the same workspace."""
        return replace(self, simulation_name=name)

    @classmethod
    def from_toml(cls, path: Path, *, root: RootConfig | None = None) -> CatchmentReportInputs:
        return cls.from_settings(CatchmentReportSettings.from_toml(path), root=root)

    @classmethod
    def from_settings(
        cls,
        settings: CatchmentReportSettings,
        *,
        root: RootConfig | None = None,
    ) -> CatchmentReportInputs:
        observed = settings.observed_discharge
        return cls.from_project_layout(
            site_label=settings.report.site_label,
            station_label=settings.report.station_label,
            title=settings.report.title,
            preset_name=settings.report.preset,
            watershed_project_dir=settings.layout.watershed_project_dir,
            data_overview_project_dir=settings.layout.data_overview_project_dir,
            simulation_workspace_dir=settings.layout.simulation_workspace_dir,
            simulation_name=settings.layout.simulation_name,
            context_summary_name=settings.layout.context_summary_name,
            transient_config_name=settings.layout.transient_config_name,
            overview_config_name=settings.layout.overview_config_name,
            observed_discharge_path=observed.path if observed else None,
            observed_discharge_station_id=observed.station_id if observed else None,
            geology_path=settings.geology.path if settings.geology else None,
            pipeline_run_overview=settings.pipeline.run_overview,
            pipeline_run_simulation=settings.pipeline.run_simulation,
            pipeline_build_context_artifacts=settings.pipeline.build_context_artifacts,
            pipeline_build_report_html=settings.pipeline.build_report_html,
            pipeline_stream_run_logs=settings.pipeline.stream_run_logs,
            pipeline_strict_figure_postflight=settings.pipeline.strict_figure_postflight,
            root=root,
        )

    @classmethod
    def from_project_layout(
        cls,
        *,
        site_label: str,
        station_label: str,
        watershed_project_dir: Path,
        data_overview_project_dir: Path | None = None,
        simulation_workspace_dir: Path | None = None,
        simulation_name: str = "transient_nwt",
        title: str = "",
        context_summary_name: str | None = None,
        transient_config_name: str | None = None,
        overview_config_name: str | None = None,
        observed_discharge_path: Path | None = None,
        observed_discharge_station_id: str | None = None,
        geology_path: Path | None = None,
        preset_name: str | None = None,
        pipeline_run_overview: bool = False,
        pipeline_run_simulation: bool = False,
        pipeline_build_context_artifacts: bool = True,
        pipeline_build_report_html: bool = True,
        pipeline_stream_run_logs: bool = False,
        pipeline_strict_figure_postflight: bool = False,
        root: RootConfig | None = None,
    ) -> CatchmentReportInputs:
        data_overview_project_dir = data_overview_project_dir or watershed_project_dir
        simulation_workspace_dir = simulation_workspace_dir or watershed_project_dir
        context_summary_name = (
            context_summary_name or f"{_slug(site_label)}_gauged_context_summary.json"
        )
        transient_config_name = transient_config_name or f"run_{simulation_name}.toml"
        overview_config_name = overview_config_name or "config_overview.toml"
        return cls(
            site_label=site_label,
            station_label=station_label,
            watershed_project_dir=watershed_project_dir,
            data_overview_project_dir=data_overview_project_dir,
            simulation_workspace_dir=simulation_workspace_dir,
            simulation_name=simulation_name,
            context_summary_name=context_summary_name,
            geographic_scratch=_kept_geographic(simulation_workspace_dir),
            generated_network_root=runs_dir_for(simulation_workspace_dir),
            transient_config=(watershed_project_dir / transient_config_name).resolve(),
            overview_config=(data_overview_project_dir / overview_config_name).resolve(),
            title=title,
            observed_discharge_path=observed_discharge_path,
            observed_discharge_station_id=observed_discharge_station_id,
            geology_path=geology_path,
            preset_name=preset_name,
            pipeline_run_overview=pipeline_run_overview,
            pipeline_run_simulation=pipeline_run_simulation,
            pipeline_build_context_artifacts=pipeline_build_context_artifacts,
            pipeline_build_report_html=pipeline_build_report_html,
            pipeline_stream_run_logs=pipeline_stream_run_logs,
            pipeline_strict_figure_postflight=pipeline_strict_figure_postflight,
            root=root,
        )


def _kept_geographic(project_dir: Path) -> Path:
    """Return the geographic folder the simulation run kept, or where it would sit."""
    kept = kept_preprocessing_dir(project_dir)
    return (kept or preprocessing_dir(project_dir)) / "geographic"


def _slug(value: str) -> str:
    cleaned = "".join(char.lower() if char.isalnum() else "_" for char in value)
    parts = [part for part in cleaned.split("_") if part]
    return "_".join(parts)


__all__ = ["CONTEXT_DIRNAME", "CatchmentReportInputs"]
