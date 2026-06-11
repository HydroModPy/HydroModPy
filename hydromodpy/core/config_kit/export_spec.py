"""Declarative description of a single result export.

One :class:`ExportSpec` == one output artifact. The same model is built from
the Python facade (``run.export``), the CLI, and the TOML
``[[export.artifacts]]`` section, so selection and
validation live in exactly one place. It mirrors the ``hmp.read`` selector
(``var`` / ``time`` / ``layer``) and adds the output format, destination, and
raster options.

Lives in ``core.config_kit`` (next to :class:`HydroModelBase`) because both
``results`` and ``simulation`` build it, and ``core`` is the only layer both
may import without creating a cycle.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, model_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile


class ExportFormat(StrEnum):
    """Output formats reachable through the unified export engine."""

    csv = "csv"
    netcdf = "netcdf"
    geotiff = "geotiff"
    shapefile = "shapefile"
    vtu = "vtu"
    hmp = "hmp"


# File extension -> format. Single source of truth for extension sniffing.
_SUFFIX_TO_FORMAT: dict[str, ExportFormat] = {
    ".csv": ExportFormat.csv,
    ".nc": ExportFormat.netcdf,
    ".tif": ExportFormat.geotiff,
    ".tiff": ExportFormat.geotiff,
    ".shp": ExportFormat.shapefile,
    ".vtu": ExportFormat.vtu,
    ".hmp": ExportFormat.hmp,
}

# Formats that render exactly one timestep per file.
_SINGLE_TIMESTEP = frozenset({ExportFormat.geotiff, ExportFormat.shapefile, ExportFormat.vtu})


def format_from_path(path: str | Path) -> ExportFormat | None:
    """Infer an :class:`ExportFormat` from a file extension, or None."""
    return _SUFFIX_TO_FORMAT.get(Path(path).suffix.lower())


class ExportSpec(HydroModelBase):
    """One export artifact: what to select, in which format, where to write.

    ``fmt`` is optional when ``dest`` carries a known extension
    (``.nc`` -> netcdf, ``.tif`` -> geotiff, ``.csv`` -> csv ...).
    """

    var: Annotated[str | list[str], Profile.USER] = Field(
        description="Variable name, list of names, or '*' (all timeseries, csv only).",
    )
    dest: Annotated[Path, Profile.USER] = Field(
        description="Output file path. Its extension can imply 'fmt'.",
    )
    fmt: Annotated[ExportFormat | None, Profile.USER] = Field(
        default=None,
        description="Output format. Inferred from the 'dest' extension when omitted.",
    )
    time: Annotated[int | list[int] | Literal["first", "last", "all"] | None, Profile.USER] = Field(
        default=None,
        description=(
            "Timestep selector: index, list of indices, 'first', 'last', 'all', or None "
            "(per-format default: all timesteps for netcdf, last for rasters)."
        ),
    )
    layer: Annotated[int | None, Profile.DEV] = Field(
        default=None,
        description="Layer index for 3D fields.",
    )
    resolution: Annotated[float | None, Profile.DEV] = Field(
        default=None,
        description="GeoTIFF pixel size in CRS units. Auto-derived from the grid when omitted.",
    )
    crs: Annotated[str | None, Profile.DEV] = Field(
        default=None,
        description="Output CRS (e.g. 'EPSG:2154'). Auto-filled from the simulation when omitted.",
    )
    nodata: Annotated[float, Profile.DEV] = Field(
        default=-9999.0,
        description="Nodata fill value for raster formats.",
    )

    @model_validator(mode="after")
    def _resolve_and_check(self) -> ExportSpec:
        if self.fmt is None:
            inferred = format_from_path(self.dest)
            if inferred is None:
                raise ValueError(
                    f"Cannot infer export format from '{self.dest}'. Set 'fmt' "
                    f"explicitly or use a known extension "
                    f"({', '.join(sorted(_SUFFIX_TO_FORMAT))})."
                )
            object.__setattr__(self, "fmt", inferred)
        if self.fmt in _SINGLE_TIMESTEP and (self.time == "all" or isinstance(self.time, list)):
            raise ValueError(
                f"time={self.time!r} selects multiple timesteps, invalid for "
                f"'{self.fmt.value}' (one timestep per file). Use an index, 'first', or 'last'."
            )
        return self

    @property
    def var_list(self) -> list[str]:
        """Variables as a list (single string -> one-element list)."""
        return [self.var] if isinstance(self.var, str) else list(self.var)


__all__ = ["ExportFormat", "ExportSpec", "format_from_path"]
