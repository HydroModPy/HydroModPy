"""Pydantic configuration models for ``[simulation.results]``."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.persistence import PersistenceConfig
from hydromodpy.core.config_kit.profile import Profile


class DerivedConfig(HydroModelBase):
    """Toggle flags for derived variable computation."""

    watertable_elevation: Annotated[bool, Profile.USER] = Field(
        default=True,
        description="Compute water-table elevation from uppermost saturated layer.",
    )
    watertable_depth: Annotated[bool, Profile.USER] = Field(
        default=True,
        description="Compute water-table depth (surface minus water-table elevation).",
    )
    seepage_areas: Annotated[bool, Profile.USER] = Field(
        default=True,
        description="Identify seepage areas where water table >= surface elevation.",
    )
    groundwater_flux: Annotated[bool, Profile.DEV] = Field(
        default=False,
        description="Magnitude of inter-cell flow (right/front/lower face). Volumetric.",
    )
    accumulation_flux: Annotated[bool, Profile.DEV] = Field(
        default=True,
        description="Drain flux routed on the drainage network.",
    )
    outflow_drain: Annotated[bool, Profile.DEV] = Field(
        default=True,
        description="Positive per-cell drain outflow summed over layers.",
    )
    concentration_seepage: Annotated[bool, Profile.DEV] = Field(
        default=False,
        description="Concentration at seepage cells only. Requires transport.",
    )
    mass_seepage: Annotated[bool, Profile.DEV] = Field(
        default=False,
        description="Mass flux at seepage cells. Requires transport + budget.",
    )
    mass_accumulated: Annotated[bool, Profile.DEV] = Field(
        default=False,
        description="Cumulative mass_seepage over time.",
    )


class ExportVariablesConfig(HydroModelBase):
    """Which variables to include in automated exports."""

    head: Annotated[bool, Profile.USER] = Field(default=True, description="Export head field.")
    concentration: Annotated[bool, Profile.USER] = Field(
        default=False, description="Export concentration field."
    )
    budget: Annotated[bool, Profile.DEV] = Field(
        default=False, description="Export spatial budget fields."
    )
    pathlines: Annotated[bool, Profile.DEV] = Field(
        default=False, description="Export pathline data."
    )
    derived: Annotated[bool, Profile.USER] = Field(
        default=True,
        description="Export derived variables (watertable_depth, seepage_mask, etc.).",
    )

    def active_names(self) -> list[str]:
        """Return list of enabled variable names."""
        names = []
        if self.head:
            names.append("head")
        if self.concentration:
            names.append("concentration")
        if self.derived:
            names.extend(["watertable_elevation", "watertable_depth", "seepage_mask"])
        return names


class ExportConfig(HydroModelBase):
    """Automated export configuration."""

    netcdf: Annotated[bool, Profile.USER] = Field(
        default=False, description="Export to NetCDF-4/UGRID."
    )
    csv_timeseries: Annotated[bool, Profile.USER] = Field(
        default=True, description="Export time series to CSV."
    )
    vtu: Annotated[bool, Profile.DEV] = Field(
        default=False, description="Export to VTU (ParaView)."
    )
    geotiff: Annotated[bool, Profile.DEV] = Field(default=False, description="Export to GeoTIFF.")
    shapefile: Annotated[bool, Profile.DEV] = Field(
        default=False, description="Export to Shapefile."
    )
    output_dir: Annotated[str | None, Profile.DEV] = Field(
        default=None,
        description="Output directory for exports. Defaults to project results folder.",
    )
    variables: Annotated[ExportVariablesConfig, Profile.USER] = Field(
        default_factory=ExportVariablesConfig,
        description="Which variables to include in exports.",
    )

    def any_enabled(self) -> bool:
        """Return True if at least one export format is enabled."""
        return any([self.netcdf, self.csv_timeseries, self.vtu, self.geotiff, self.shapefile])


class BudgetConfig(HydroModelBase):
    """Budget extraction configuration."""

    spatial_fields: Annotated[bool, Profile.DEV] = Field(
        default=True,
        description="Extract per-cell budget fields (DRN, RCH, etc.) into Zarr.",
    )


class ResultsConfig(HydroModelBase):
    """Configuration for ``[simulation.results]``.

    Controls whether simulation outputs are stored in the SimulationCatalog,
    which derived variables are computed, and which export formats are
    produced automatically after each run.
    """

    persistence: Annotated[PersistenceConfig, Profile.USER] = Field(
        default_factory=PersistenceConfig,
        description=(
            "Simulation-run persistence switch passed to the result catalog "
            "(DuckDB rows, Zarr fields, Parquet tables, lockfile)."
        ),
    )
    keep_solver_files: Annotated[bool, Profile.DEV] = Field(
        default=False,
        description="Keep raw solver output files (.hds, .cbc, .lst) after ingestion.",
    )
    solver_scratch: Annotated[str, Profile.DEV] = Field(
        default=".solver_scratch",
        description=(
            "Directory for temporary solver files, relative to the project. "
            "Use an absolute path (e.g. /scratch/$USER/hmp) for HPC."
        ),
    )
    derived: Annotated[DerivedConfig, Profile.USER] = Field(
        default_factory=DerivedConfig,
        description="Derived variable computation toggles.",
    )
    budget: Annotated[BudgetConfig, Profile.DEV] = Field(
        default_factory=BudgetConfig,
        description="Budget extraction configuration.",
    )
    export: Annotated[ExportConfig, Profile.USER] = Field(
        default_factory=ExportConfig,
        description="Automated export configuration.",
    )


__all__ = [
    "BudgetConfig",
    "DerivedConfig",
    "ExportConfig",
    "ExportVariablesConfig",
    "ResultsConfig",
]
