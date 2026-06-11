"""Pydantic configuration model for the top-level ``[export]`` section.

``[export]`` is the run's automated-export contract: which formats to write at
the end of a solve, which variables, which timesteps, and whether to also emit a
portable ``.hmp`` archive. It is a top-level section (``cfg.export``) rather than
nested under ``[simulation.results]`` so the most user-facing block is the
shallowest to reach.

Lives in the ``simulation`` layer because the post-run export hook
(``simulation.extraction.post_run``) consumes it, and ``config`` (which exposes
it on :class:`HydroModPyConfig`) may import ``simulation``.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.export_spec import ExportSpec
from hydromodpy.core.config_kit.profile import Profile

TimesSelector = int | list[int] | Literal["first", "last", "all"]


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
    """Automated export configuration loaded from the top-level ``[export]`` section."""

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
    package: Annotated[bool, Profile.USER] = Field(
        default=False,
        description=(
            "Also write a portable '<run>.hmp' archive (config, provenance, fields, "
            "timeseries, RO-Crate) after the run finalizes. The one-line switch for "
            "'this run must be shareable forever'."
        ),
    )
    output_dir: Annotated[str | None, Profile.DEV] = Field(
        default=None,
        description="Output directory for exports. Defaults to project results folder.",
    )
    variables: Annotated[ExportVariablesConfig, Profile.USER] = Field(
        default_factory=ExportVariablesConfig,
        description="Which variables to include in exports.",
    )
    times: Annotated[TimesSelector, Profile.USER] = Field(
        default="last",
        description=(
            "Timestep selector for field/raster exports: 'first', 'last', 'all', a "
            "timestep index, or a list of indices. Time-series CSV always covers all steps."
        ),
    )
    resolution: Annotated[float | None, Profile.DEV] = Field(
        default=None,
        description=(
            "GeoTIFF pixel size in CRS units for toggle exports. "
            "Auto-derived from the grid when omitted."
        ),
    )
    artifacts: Annotated[list[ExportSpec], Profile.DEV] = Field(
        default_factory=list,
        description=(
            "Explicit export artifacts: full control over variable, format, "
            "timestep and destination, beyond the format toggles above."
        ),
    )

    def any_enabled(self) -> bool:
        """Return True if at least one export format toggle is enabled."""
        return any([self.netcdf, self.csv_timeseries, self.vtu, self.geotiff, self.shapefile])


__all__ = [
    "ExportConfig",
    "ExportVariablesConfig",
    "TimesSelector",
]
