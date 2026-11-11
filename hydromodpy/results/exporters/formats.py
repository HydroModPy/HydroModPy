"""The six file formats the wheel writes an export with.

Each one is a declaration on the export port
(:mod:`hydromodpy.results.exporters.port`) and a thin dispatch: the writing
itself lives on :class:`~hydromodpy.results.exporters.job.ExportJob`, the one
object that reads the run, so the body of a format decision is one line a
kind. The seventh shipped format, the RO-Crate view, is declared where it
lives, in :mod:`hydromodpy.results.export.rocrate`.

A new format of the wheel is a writer here, its dotted path in ``_BUILTIN_PATHS`` of
``registry.py`` and a case in ``tests/ports/test_export.py``.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

from hydromodpy.results.exporters.export_spec import ExportKind

if TYPE_CHECKING:
    from hydromodpy.results.exporters.export_spec import PlannedFile
    from hydromodpy.results.exporters.job import ExportJob


class _FileFormat:
    """What the six file formats share: one kind-checked dispatch to the job."""

    name: ClassVar[str]
    suffix: ClassVar[str]
    writes: ClassVar[tuple[str, ...]]
    natural: ClassVar[tuple[str, ...]]
    instants: ClassVar[str]
    reprojects: ClassVar[bool]
    help: ClassVar[str]

    def write(
        self,
        job: ExportJob | None,
        item: PlannedFile,
        dest: Path,
    ) -> list[Path]:
        """Write one planned file of this format at *dest*.

        The format decides, the job writes: the method named for the kind of
        the planned item lives on the job, the one object that reads the run.
        """
        assert item is not None
        assert job is not None
        kind = job.kinds[item.variables[0]] if item.variables else None
        methods = self._by_kind()
        if kind not in methods:
            raise self._refused(item, kind)
        written = getattr(job, methods[str(kind)])(item, dest)
        return written if isinstance(written, list) else [written]

    def _by_kind(self) -> dict[str, str]:
        """The job method that writes each kind this format holds."""
        raise NotImplementedError

    def _refused(self, item: PlannedFile, kind: str | None) -> Exception:
        from hydromodpy.core.exceptions import ExportError

        return ExportError(
            f"nothing writes {item.path} as {self.name}: a {kind} does not go to this format."
        )


class NetcdfFormat(_FileFormat):
    """One NetCDF file holding every field of the request over the record."""

    name: ClassVar[str] = "netcdf"
    suffix: ClassVar[str] = ".nc"
    writes: ClassVar[tuple[str, ...]] = (ExportKind.field,)
    natural: ClassVar[tuple[str, ...]] = (ExportKind.field,)
    instants: ClassVar[str] = "many"
    reprojects: ClassVar[bool] = False
    help: ClassVar[str] = "A NetCDF file (.nc): fields and series over time."

    def _by_kind(self) -> dict[str, str]:
        return {ExportKind.field: "_netcdf"}


class GeotiffFormat(_FileFormat):
    """A GeoTIFF raster, one file per date of a field, the raster layers in one."""

    name: ClassVar[str] = "geotiff"
    suffix: ClassVar[str] = ".tif"
    writes: ClassVar[tuple[str, ...]] = (ExportKind.field, ExportKind.raster)
    natural: ClassVar[tuple[str, ...]] = (ExportKind.raster,)
    instants: ClassVar[str] = "one"
    reprojects: ClassVar[bool] = True
    help: ClassVar[str] = "A GeoTIFF raster (.tif), one file per date."

    def _by_kind(self) -> dict[str, str]:
        return {ExportKind.field: "_field_instants", ExportKind.raster: "_raster"}


class CsvFormat(_FileFormat):
    """CSV tables: the series and the budget."""

    name: ClassVar[str] = "csv"
    suffix: ClassVar[str] = ".csv"
    writes: ClassVar[tuple[str, ...]] = (ExportKind.series, ExportKind.table)
    natural: ClassVar[tuple[str, ...]] = (ExportKind.series, ExportKind.table)
    instants: ClassVar[str] = "many"
    reprojects: ClassVar[bool] = False
    help: ClassVar[str] = "A CSV table (.csv): series and tables."

    def _by_kind(self) -> dict[str, str]:
        return {ExportKind.series: "_series", ExportKind.table: "_budget"}


class GeopackageFormat(_FileFormat):
    """A GeoPackage vector file; the mesh layers of a run share one file."""

    name: ClassVar[str] = "geopackage"
    suffix: ClassVar[str] = ".gpkg"
    writes: ClassVar[tuple[str, ...]] = (ExportKind.field, ExportKind.vector)
    natural: ClassVar[tuple[str, ...]] = (ExportKind.vector,)
    instants: ClassVar[str] = "one"
    reprojects: ClassVar[bool] = True
    help: ClassVar[str] = (
        "A GeoPackage vector file (.gpkg), one file per date. The mesh layers of a run "
        "share one file."
    )

    def _by_kind(self) -> dict[str, str]:
        return {ExportKind.field: "_field_instants", ExportKind.vector: "_vector"}


class ShapefileFormat(_FileFormat):
    """An ESRI Shapefile, one layer a file, one file per date of a field."""

    name: ClassVar[str] = "shapefile"
    suffix: ClassVar[str] = ".shp"
    writes: ClassVar[tuple[str, ...]] = (ExportKind.field, ExportKind.vector)
    natural: ClassVar[tuple[str, ...]] = ()
    instants: ClassVar[str] = "one"
    reprojects: ClassVar[bool] = True
    help: ClassVar[str] = "An ESRI Shapefile (.shp), one file per date."

    def _by_kind(self) -> dict[str, str]:
        return {ExportKind.field: "_field_instants", ExportKind.vector: "_vector"}


class VtuFormat(_FileFormat):
    """A VTK unstructured grid of the mesh, holding one field by date."""

    name: ClassVar[str] = "vtu"
    suffix: ClassVar[str] = ".vtu"
    writes: ClassVar[tuple[str, ...]] = (ExportKind.field,)
    natural: ClassVar[tuple[str, ...]] = ()
    instants: ClassVar[str] = "one"
    reprojects: ClassVar[bool] = False
    help: ClassVar[str] = "A VTK unstructured grid (.vtu) of the mesh, one file per date."

    def _by_kind(self) -> dict[str, str]:
        return {ExportKind.field: "_field_instants"}


__all__ = [
    "CsvFormat",
    "GeopackageFormat",
    "GeotiffFormat",
    "NetcdfFormat",
    "ShapefileFormat",
    "VtuFormat",
]
