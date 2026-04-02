"""Pydantic configuration models for ``[simulation.results]``."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class DerivedConfig(BaseModel):
    """Toggle flags for derived variable computation."""

    model_config = ConfigDict(extra="forbid")

    watertable_elevation: bool = Field(
        default=True,
        description="Compute water-table elevation from uppermost saturated layer.",
    )
    watertable_depth: bool = Field(
        default=True,
        description="Compute water-table depth (surface minus water-table elevation).",
    )
    seepage_areas: bool = Field(
        default=True,
        description="Identify seepage areas where water table >= surface elevation.",
    )


class ExportVariablesConfig(BaseModel):
    """Which variables to include in automated exports."""

    model_config = ConfigDict(extra="forbid")

    head: bool = Field(default=True, description="Export head field.")
    concentration: bool = Field(default=False, description="Export concentration field.")
    budget: bool = Field(default=False, description="Export spatial budget fields.")
    pathlines: bool = Field(default=False, description="Export pathline data.")
    derived: bool = Field(
        default=True,
        description="Export derived variables (watertable_depth, seepage_areas, etc.).",
    )

    def active_names(self) -> list[str]:
        """Return list of enabled variable names."""
        names = []
        if self.head:
            names.append("head")
        if self.concentration:
            names.append("concentration")
        if self.derived:
            names.extend(["watertable_elevation", "watertable_depth", "seepage_areas"])
        return names


class ExportConfig(BaseModel):
    """Automated export configuration."""

    model_config = ConfigDict(extra="forbid")

    netcdf: bool = Field(default=False, description="Export to NetCDF-4/UGRID.")
    csv_timeseries: bool = Field(default=False, description="Export time series to CSV.")
    vtu: bool = Field(default=False, description="Export to VTU (ParaView).")
    geotiff: bool = Field(default=False, description="Export to GeoTIFF.")
    shapefile: bool = Field(default=False, description="Export to Shapefile.")
    output_dir: str | None = Field(
        default=None,
        description="Output directory for exports. Defaults to project results folder.",
    )
    variables: ExportVariablesConfig = Field(
        default_factory=ExportVariablesConfig,
        description="Which variables to include in exports.",
    )

    def any_enabled(self) -> bool:
        """Return True if at least one export format is enabled."""
        return any([self.netcdf, self.csv_timeseries, self.vtu, self.geotiff, self.shapefile])


class BudgetConfig(BaseModel):
    """Budget extraction configuration."""

    model_config = ConfigDict(extra="forbid")

    spatial_fields: bool = Field(
        default=False,
        description="Extract per-cell budget fields (DRN, RCH, etc.) into Zarr.",
    )


class ResultsConfig(BaseModel):
    """Configuration for ``[simulation.results]``.

    Controls whether simulation outputs are stored in the ResultStore,
    which derived variables are computed, and which export formats are
    produced automatically after each run.
    """

    model_config = ConfigDict(extra="forbid")

    store: bool = Field(
        default=True,
        description="Store simulation outputs in the ResultStore (DuckDB + Zarr).",
    )
    keep_solver_files: bool = Field(
        default=False,
        description="Keep raw solver output files (.hds, .cbc, .lst) after ingestion.",
    )
    derived: DerivedConfig = Field(
        default_factory=DerivedConfig,
        description="Derived variable computation toggles.",
    )
    budget: BudgetConfig = Field(
        default_factory=BudgetConfig,
        description="Budget extraction configuration.",
    )
    export: ExportConfig = Field(
        default_factory=ExportConfig,
        description="Automated export configuration.",
    )
