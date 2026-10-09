"""TOML-backed settings for catchment reports.

The report file is validated by Pydantic models. A key the models do not know is
refused, so a typo cannot silently fall back on a default. Every field carries a
description, which is the source a reference page is generated from.
"""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import Field, StrictBool, ValidationError

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.exceptions import ConfigValidationError
from hydromodpy.core.toml_io.error_locator import (
    format_validation_error,
    validation_error_details,
)

PresetName = Literal["generic", "generic_catchment_report"]
"""The names ``PRESETS_BY_NAME`` in ``presets.py`` answers to."""


class ReportSection(HydroModelBase):
    """The ``[report]`` table: what the report is called and where it is written."""

    output_dir: Annotated[Path, Profile.USER] = Field(
        ...,
        description=(
            "Folder of the report. The page is written to <output_dir>/web/index.html. "
            "A relative path is resolved from the folder that holds the report file."
        ),
        examples=["outputs/report"],
    )
    site_label: Annotated[str, Profile.USER] = Field(
        ...,
        min_length=1,
        description="Catchment name used in the titles of the report.",
        examples=["Upper basin"],
    )
    station_label: Annotated[str, Profile.USER] = Field(
        ...,
        min_length=1,
        description="Gauge or outlet name used in the site block of the report.",
        examples=["Basin outlet"],
    )
    title: Annotated[str, Profile.USER] = Field(
        "",
        description="Replaces the title of the report page. Empty keeps the generated title.",
    )
    preset: Annotated[PresetName | None, Profile.USER] = Field(
        None,
        description=(
            "Report preset: the set of figures and blocks the page is built from. "
            "'generic' is an alias of 'generic_catchment_report'. Empty uses the generic preset."
        ),
    )


class LayoutSection(HydroModelBase):
    """The ``[layout]`` table: where the projects, runs and context files sit."""

    watershed_project_dir: Annotated[Path, Profile.USER] = Field(
        ...,
        description=(
            "Project folder that holds the simulation file. A relative path is resolved "
            "from the folder that holds the report file."
        ),
        examples=["."],
    )
    context_outputs_dir: Annotated[Path, Profile.USER] = Field(
        ...,
        description=(
            "Folder that receives the context files, under context/ and web/assets/. "
            "A relative path is resolved from the folder that holds the report file."
        ),
        examples=["outputs/context"],
    )
    data_overview_project_dir: Annotated[Path | None, Profile.USER] = Field(
        None,
        description=(
            "Project that holds the overview figures and the overview file. "
            "Empty uses watershed_project_dir."
        ),
    )
    simulation_workspace_dir: Annotated[Path | None, Profile.USER] = Field(
        None,
        description=(
            "Project that holds the run catalog and the run to describe. "
            "Empty uses watershed_project_dir."
        ),
    )
    simulation_name: Annotated[str, Profile.USER] = Field(
        "transient_nwt",
        min_length=1,
        description=(
            "Name of the run to describe. It must be the simulation.name of the simulation "
            "file. A name written with a version, such as 'run.v2', is read as written."
        ),
    )
    context_summary_name: Annotated[str | None, Profile.USER] = Field(
        None,
        description=(
            "File name of the context summary under <context_outputs_dir>/context. "
            "Empty uses the only *_gauged_context_summary.json found there, or a name "
            "derived from site_label."
        ),
    )
    transient_config_name: Annotated[str | None, Profile.USER] = Field(
        None,
        description=(
            "Simulation file, relative to watershed_project_dir. "
            "Empty uses run_<simulation_name>.toml."
        ),
    )
    overview_config_name: Annotated[str | None, Profile.USER] = Field(
        None,
        description=(
            "Overview file, relative to data_overview_project_dir. Empty uses config_overview.toml."
        ),
    )


class ObservedDischargeSection(HydroModelBase):
    """The ``[context.observed_discharge]`` table: the gauge record shown beside the run."""

    path: Annotated[Path, Profile.USER] = Field(
        ...,
        description=(
            "CSV file of observed discharge, with the columns datetime and value. "
            "A relative path is resolved from the folder that holds the report file. "
            "Observed discharge is a figure and a diagnostic of the report, never a model input."
        ),
        examples=["observed/discharge.csv"],
    )
    station_id: Annotated[str | None, Profile.USER] = Field(
        None,
        description="Identifier of the gauge, written in the context summary.",
    )


class GeologySection(HydroModelBase):
    """The ``[context.geology]`` table: the geological map the legend is read from."""

    path: Annotated[Path, Profile.USER] = Field(
        ...,
        description=(
            "Vector file (GeoPackage or shapefile) of the geological map, with a legend code "
            "column such as CODE_LEG. A relative path is resolved from the folder that holds "
            "the report file. Without this table, the BRGM GeoPackages that the geology "
            "loader cached for the user are tried."
        ),
        examples=["geology/map.gpkg"],
    )


class ContextSection(HydroModelBase):
    """The ``[context]`` table: data the report shows beside the run."""

    observed_discharge: Annotated[ObservedDischargeSection | None, Profile.USER] = Field(
        None,
        description="Observed discharge record of the gauge. Empty shows the simulation alone.",
    )
    geology: Annotated[GeologySection | None, Profile.USER] = Field(
        None,
        description="Geological map the legend table is read from. Empty uses the geology cache.",
    )


class PipelineSection(HydroModelBase):
    """The ``[pipeline]`` table: which steps run when the command has no option."""

    run_overview: Annotated[StrictBool, Profile.USER] = Field(
        False,
        description="Run the overview file first.",
    )
    run_simulation: Annotated[StrictBool, Profile.USER] = Field(
        False,
        description="Run the simulation file first.",
    )
    build_context_artifacts: Annotated[StrictBool, Profile.USER] = Field(
        True,
        description="Build the context summary, its page and its images.",
    )
    build_report_html: Annotated[StrictBool, Profile.USER] = Field(
        True,
        description="Build the report page.",
    )
    no_lock: Annotated[StrictBool, Profile.USER] = Field(
        True,
        description="Pass --no-lock to the overview run and the simulation run.",
    )
    stream_run_logs: Annotated[StrictBool, Profile.USER] = Field(
        False,
        description="Print the logs of the overview and simulation runs instead of keeping them.",
    )
    strict_figure_postflight: Annotated[StrictBool, Profile.USER] = Field(
        False,
        description=(
            "Fail the command when an expected figure is missing. "
            "The expected list holds every figure of the preset, optional ones included."
        ),
    )


class ReportConfig(HydroModelBase):
    """The catchment report file read by ``hmp report catchment``."""

    report: Annotated[ReportSection, Profile.USER] = Field(
        ...,
        description="Name, labels and output folder of the report.",
    )
    layout: Annotated[LayoutSection, Profile.USER] = Field(
        ...,
        description="Where the projects, the run and the context files sit.",
    )
    context: Annotated[ContextSection, Profile.USER] = Field(
        default_factory=ContextSection,
        description="Data the report shows beside the run.",
    )
    pipeline: Annotated[PipelineSection, Profile.USER] = Field(
        default_factory=PipelineSection,
        description="Steps that run when the command has no option.",
    )


@dataclass(frozen=True)
class CatchmentReportSettings:
    """The validated report file, with every path resolved from the file's folder."""

    report: ReportSection
    layout: LayoutSection
    observed_discharge: ObservedDischargeSection | None
    geology: GeologySection | None
    pipeline: PipelineSection

    @classmethod
    def from_toml(cls, path: Path) -> CatchmentReportSettings:
        config_path = Path(path).expanduser().resolve()
        payload = tomllib.loads(config_path.read_text(encoding="utf-8-sig"))
        return cls.from_mapping(payload, base_dir=config_path.parent, source_path=config_path)

    @classmethod
    def from_mapping(
        cls,
        payload: Mapping[str, Any],
        *,
        base_dir: Path,
        source_path: Path | None = None,
    ) -> CatchmentReportSettings:
        try:
            config = ReportConfig.model_validate(dict(payload))
        except ValidationError as exc:
            raise ConfigValidationError(
                format_validation_error(exc, source_path=source_path, document=payload),
                details=validation_error_details(exc, source_path=source_path, document=payload),
                source=None if source_path is None else str(source_path),
            ) from exc
        return cls.from_config(config, base_dir=base_dir)

    @classmethod
    def from_config(cls, config: ReportConfig, *, base_dir: Path) -> CatchmentReportSettings:
        """Resolve the paths of a validated report file against ``base_dir``."""
        layout = config.layout
        watershed_project_dir = _path(base_dir, layout.watershed_project_dir)
        resolved_layout = layout.model_copy(
            update={
                "watershed_project_dir": watershed_project_dir,
                "context_outputs_dir": _path(base_dir, layout.context_outputs_dir),
                "data_overview_project_dir": _path(
                    base_dir, layout.data_overview_project_dir or watershed_project_dir
                ),
                "simulation_workspace_dir": _path(
                    base_dir, layout.simulation_workspace_dir or watershed_project_dir
                ),
            }
        )
        observed = config.context.observed_discharge
        if observed is not None:
            observed = observed.model_copy(update={"path": _path(base_dir, observed.path)})
        geology = config.context.geology
        if geology is not None:
            geology = geology.model_copy(update={"path": _path(base_dir, geology.path)})
        return cls(
            report=config.report.model_copy(
                update={"output_dir": _path(base_dir, config.report.output_dir)}
            ),
            layout=resolved_layout,
            observed_discharge=observed,
            geology=geology,
            pipeline=config.pipeline,
        )


def _path(base_dir: Path, value: Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = base_dir / path
    return path.resolve()


__all__ = [
    "CatchmentReportSettings",
    "ContextSection",
    "GeologySection",
    "LayoutSection",
    "ObservedDischargeSection",
    "PipelineSection",
    "PresetName",
    "ReportConfig",
    "ReportSection",
]
