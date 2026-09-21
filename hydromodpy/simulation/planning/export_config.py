"""Pydantic configuration model for the top-level ``[export]`` section.

``[export]`` is the run's automated-export contract: which formats to write at
the end of a solve, which variables, which timestep, and whether to also emit a
portable ``.hmp`` archive. It is a top-level section (``cfg.export``) rather than
nested under ``[simulation.results]`` so the most user-facing block is the
shallowest to reach.

Lives in the ``simulation`` layer because the post-run export hook
(``simulation.extraction.post_run``) consumes it, and ``config`` (which exposes
it on :class:`HydroModPyConfig`) may import ``simulation``.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.export_spec import ExportSpec
from hydromodpy.core.config_kit.profile import Profile

TimesSelector = int | list[int] | Literal["first", "last", "all"]

# Toggles writing one timestep per file: a multi-step selector has no meaning
# for them, and a selector naming several is refused rather than collapsed.
_SINGLE_TIMESTEP_TOGGLES = ("vtu", "geotiff", "shapefile", "geopackage")

# Toggles that read ``variables``. ``csv_timeseries`` is absent on purpose: it
# exports the whole timeseries table and never looks at the variable list.
_VARIABLE_DRIVEN_TOGGLES = ("netcdf", "vtu", "geotiff", "shapefile", "geopackage")

# Toggles that write a raster, the only consumers of ``resolution``.
_RASTER_TOGGLES = ("geotiff",)


class ExportConfig(HydroModelBase):
    """Automated export configuration loaded from the top-level ``[export]`` section."""

    netcdf: Annotated[bool, Profile.USER] = Field(
        default=False, description="Export to NetCDF-4/UGRID."
    )
    csv_timeseries: Annotated[bool, Profile.USER] = Field(
        default=False,
        description=(
            "Export time series to CSV at the end of the run. Off by default: the "
            "canonical time series lives in tables.parquet; CSV is an on-demand export. "
            "The only toggle that ignores 'variables'."
        ),
    )
    vtu: Annotated[bool, Profile.USER] = Field(
        default=False, description="Export to VTU (ParaView). One timestep per file."
    )
    geotiff: Annotated[bool, Profile.USER] = Field(
        default=False, description="Export to GeoTIFF. One timestep per file."
    )
    shapefile: Annotated[bool, Profile.USER] = Field(
        default=False, description="Export to Shapefile. One timestep per file."
    )
    geopackage: Annotated[bool, Profile.USER] = Field(
        default=False, description="Export to GeoPackage. One timestep per file."
    )
    package: Annotated[bool, Profile.USER] = Field(
        default=False,
        description=(
            "Also write a portable '<run>.hmp' archive (config, provenance, fields, "
            "timeseries, RO-Crate) after the run finalizes. The one-line switch for "
            "'this run must be shareable forever'."
        ),
    )
    output_dir: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description="Output directory for exports. Defaults to project results folder.",
    )
    variables: Annotated[list[str], Profile.USER] = Field(
        default=["head"],
        description=(
            "Field names to export, e.g. ['head', 'watertable_depth']. These are the "
            "run's own field names: 'hmp data export <project> --sim <name> --list' "
            "prints the ones a given run holds. A name the field registry does not "
            "know is refused before the solve, not by this schema. One file is written "
            "per name for vtu, geotiff and shapefile; the NetCDF export holds them all. "
            "Ignored by csv_timeseries."
        ),
    )
    time: Annotated[TimesSelector, Profile.USER] = Field(
        default="last",
        description=(
            "Timestep selector for field/raster exports: 'first', 'last', 'all', a "
            "timestep index, or a list of indices. Time-series CSV always covers all "
            "steps. A vtu, a geotiff and a shapefile hold ONE timestep per file, so a "
            "selector naming several is refused while any of them is on; only the "
            "NetCDF export carries the whole selection. Same spelling as "
            "[[export.artifacts]] time."
        ),
    )
    resolution: Annotated[float | None, Profile.USER] = Field(
        default=None,
        description=(
            "GeoTIFF pixel size in CRS units for toggle exports. "
            "Auto-derived from the grid when omitted."
        ),
    )
    artifacts: Annotated[list[ExportSpec], Profile.USER] = Field(
        default_factory=list,
        description=(
            "Explicit export artifacts: full control over variable, format, "
            "timestep and destination, beyond the format toggles above."
        ),
    )

    def any_enabled(self) -> bool:
        """Return True if at least one export format toggle is enabled."""
        return any(
            [
                self.netcdf,
                self.csv_timeseries,
                self.vtu,
                self.geotiff,
                self.shapefile,
                self.geopackage,
            ]
        )

    def _enabled(self, names: tuple[str, ...]) -> list[str]:
        """Return the enabled toggles among *names*, in declaration order."""
        return [name for name in names if getattr(self, name)]

    @field_validator("time")
    @classmethod
    def _reject_empty_time(cls, value: TimesSelector) -> TimesSelector:
        """An empty list is a no-op trap; require an explicit selector."""
        if isinstance(value, list) and not value:
            raise ValueError(
                "export.time cannot be an empty list; use 'first', 'last', 'all', "
                "an index, or a non-empty list of indices."
            )
        return value

    @model_validator(mode="after")
    def _reject_multi_timestep_with_single_timestep_toggle(self) -> ExportConfig:
        """A selector naming several steps cannot feed a one-timestep format."""
        selects_many = self.time == "all" or (isinstance(self.time, list) and len(self.time) > 1)
        enabled = self._enabled(_SINGLE_TIMESTEP_TOGGLES)
        if selects_many and enabled:
            raise ValueError(
                f"export.time={self.time!r} names several timesteps, but "
                f"{', '.join(enabled)} {'holds' if len(enabled) == 1 else 'hold'} one "
                "timestep per file. Set export.time to a single index, 'first' or 'last' "
                "for them, and declare the multi-step export as its own artifact: "
                '[[export.artifacts]] var = "head", dest = "fields.nc", time = "all".'
            )
        return self

    @model_validator(mode="after")
    def _reject_toggle_without_variables(self) -> ExportConfig:
        """A format toggle with no variable to write is a silent no-op."""
        enabled = self._enabled(_VARIABLE_DRIVEN_TOGGLES)
        if enabled and not self.variables:
            raise ValueError(
                f"export.variables is empty but {', '.join(enabled)} "
                f"{'is' if len(enabled) == 1 else 'are'} enabled, so "
                f"{'that format writes' if len(enabled) == 1 else 'those formats write'} "
                'nothing. Name the fields to export, e.g. variables = ["head"], or turn '
                "the toggle off. Only export.csv_timeseries ignores export.variables."
            )
        return self

    @model_validator(mode="after")
    def _reject_resolution_without_raster(self) -> ExportConfig:
        """A pixel size with no raster to size is a silent no-op."""
        if self.resolution is not None and not self._enabled(_RASTER_TOGGLES):
            raise ValueError(
                f"export.resolution={self.resolution!r} is set but no raster format is "
                "enabled, so it sizes nothing. Set export.geotiff = true, or carry the "
                "pixel size on the artifact that writes the raster: "
                "[[export.artifacts]] resolution = ..."
            )
        return self


__all__ = [
    "ExportConfig",
    "TimesSelector",
]
