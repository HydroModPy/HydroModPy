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
    geopackage = "geopackage"
    vtu = "vtu"
    hmp = "hmp"


# File extension -> format. Single source of truth for extension sniffing.
_SUFFIX_TO_FORMAT: dict[str, ExportFormat] = {
    ".csv": ExportFormat.csv,
    ".nc": ExportFormat.netcdf,
    ".tif": ExportFormat.geotiff,
    ".tiff": ExportFormat.geotiff,
    ".shp": ExportFormat.shapefile,
    ".gpkg": ExportFormat.geopackage,
    ".vtu": ExportFormat.vtu,
    ".hmp": ExportFormat.hmp,
}

# Formats that render exactly one timestep per file.
_SINGLE_TIMESTEP = frozenset(
    {
        ExportFormat.geotiff,
        ExportFormat.shapefile,
        ExportFormat.geopackage,
        ExportFormat.vtu,
    }
)


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
    resolution: Annotated[float | None, Profile.USER] = Field(
        default=None,
        description="GeoTIFF pixel size in CRS units. Auto-derived from the grid when omitted.",
    )
    crs: Annotated[str | None, Profile.DEV] = Field(
        default=None,
        description=(
            "Internal only, and always None: the exporter reads the simulation's own "
            "CRS when this stays unset, and a user-written value is refused because "
            "tagging is not reprojecting. See _resolve_and_check."
        ),
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
        else:
            # A declared format and a destination extension are two statements
            # about one file. Left unchecked, the bytes of one land under the
            # name of the other and nothing says so: a csv written as .tif opens
            # in no raster reader and looks like a corrupt file, not a mistake.
            inferred = format_from_path(self.dest)
            if inferred is not None and inferred != self.fmt:
                raise ValueError(
                    f"fmt={self.fmt.value!r} writes {self.fmt.value} bytes but dest "
                    f"{self.dest!r} names a {inferred.value} file. Drop 'fmt' to take the "
                    "extension, or give dest the extension the format writes."
                )
        if self.fmt in _SINGLE_TIMESTEP and (self.time == "all" or isinstance(self.time, list)):
            raise ValueError(
                f"time={self.time!r} selects multiple timesteps, invalid for "
                f"'{self.fmt.value}' (one timestep per file). Use an index, 'first', or 'last'."
            )
        if self.crs is not None:
            # No internal construction site sets 'crs': the exporter builds the
            # georeferencing transform from mesh/vertices in the simulation's native
            # CRS and only tags the written file with 'crs'. A user-supplied value
            # here does not reproject anything, it relabels a Lambert-93 grid as
            # whatever CRS was asked for, silently writing a file whose bounds and
            # tag disagree. Refusing any value seen here is safe for the auto-fill
            # path too, since that path never sets this field on the spec: it reads
            # 'crs' downstream (catalog.reads._export_crs_for) only when this stays None.
            raise ValueError(
                f"crs={self.crs!r} is not accepted: this exporter tags the output with "
                "the requested CRS, it does not reproject the grid, so the file would be "
                "corrupt (wrong CRS tag, native-CRS coordinates). Leave 'crs' unset to "
                "keep the simulation's native CRS, and reproject the written file "
                "afterwards (e.g. gdalwarp, rasterio.warp) if you need another one."
            )
        if isinstance(self.var, list) and len(self.var) > 1 and self.fmt in _SINGLE_TIMESTEP:
            raise ValueError(
                f"var={self.var!r} selects {len(self.var)} variables, invalid for "
                f"'{self.fmt.value}' (one variable per file, only the first would be "
                "written). Use a single variable name, or switch to 'netcdf' or 'csv' "
                "to export several at once."
            )
        return self

    @property
    def var_list(self) -> list[str]:
        """Variables as a list (single string -> one-element list)."""
        return [self.var] if isinstance(self.var, str) else list(self.var)


__all__ = ["ExportFormat", "ExportSpec", "format_from_path"]
