"""One export request: what to export, when, in which format, where.

A TOML ``[[export]]`` block, a ``run.export(...)`` call and ``hmp export``
build the same :class:`ExportRequest`, so the words and the refusals are the
same on the three surfaces. Only ``variables`` is required. The other keys say
when (``time`` or ``period``), in which format (``format``, or the extension of
``file``) and where (``folder``, ``file``). Left out, each takes the natural
answer: the whole simulation, the natural format of each data, and the
``exports/`` directory of the run. Every file lands under that directory: an
absolute ``folder`` or ``file``, or one that climbs out with ``..``, is
refused. Publishing a copy out of the project is ``hmp publish``.

The model refuses what it can decide alone, without the run and without the
kind of each name. :func:`plan_outputs` finishes the job once the kind of each
name is known: it names every file a request writes and refuses what the kinds
make impossible (a vector layer in a NetCDF, a reprojection a format cannot
carry). The loader, ``hmp check`` and the exporters all call it, so the
plan checked before the solve is the plan written after it.

A format is a name the export registry serves
(:mod:`hydromodpy.results.exporters.registry`), never an enum value here: the
registry derives the tables this module plans files with, so a format added
anywhere is refused or served everywhere on the same lines.

A new key of the ``[[export]]`` request is a field of ``ExportRequest``, and a rule on
the output path or the file name goes in ``plan_outputs``. The file name of a view is a
fact of the stored layout, in ``schema/generated_views.py``, and the ledger entry of an
export is written by ``results/ledger.py``.
"""

from __future__ import annotations

import datetime as _dt
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path, PurePath, PurePosixPath, PureWindowsPath
from typing import Annotated, Any

from pydantic import AfterValidator, Field, TypeAdapter, field_validator, model_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.field_metadata import field_metadata
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.results.exporters.destination import DELIVER_TO_KEY, parse_destination
from hydromodpy.results.exporters.registry import (
    check_format_name,
    format_suffix,
    kind_formats,
    known_extensions,
    non_reprojecting_formats,
    one_instant_formats,
    run_formats,
    suffix_format,
    view_filename,
)
from hydromodpy.schema.changes import prerelease_refusal
from hydromodpy.schema.generated_views import VIEW_FILENAMES

EXPORT_ALL = "all"
"""The ``variables`` value that asks for everything a run holds."""

STEP_DATE_TOKEN = "{date}"
"""Placeholder in a planned file name, filled with the date of each step written."""


class ExportKind(StrEnum):
    """What a name a user can export is."""

    field = "field"
    series = "series"
    table = "table"
    vector = "vector"
    raster = "raster"


MESH_LAYERS: tuple[str, ...] = ("mesh_cells", "mesh_seeds", "mesh_family_faces")
"""The vector layers of the cell mesh of a run: its cells, their seeds, the faces of its lines.

In a GeoPackage they share one file, a layer each; a Shapefile holds one layer per file."""

# The stem of a file that holds several names of one kind.
_GROUP_STEM: dict[ExportKind, str] = {ExportKind.field: "fields", ExportKind.series: "series"}


def _the_format_help(schema: dict[str, Any]) -> None:
    """Fill the value docs of the format field from the formats this build ships."""
    from hydromodpy.results.exporters.registry import export_formats, format_help

    schema["value_docs"] = {
        name: format_help(name) for name in export_formats.names(shipped_only=True)
    }


RETIRED_FORMATS: dict[str, str] = {
    "package": (
        'format = "package" is retired: the portable archive of a run is '
        "'hmp publish <run> --to DEST --container tar' (a copy carries its inputs unless it "
        "was published with --without inputs). "
        "Drop this [[export]] block."
    ),
}
"""Format names no longer written, and the sentence that names what replaces them."""

_KEYWORDS = ("first", "last")
_TIME_HELP = 'a date "YYYY-MM-DD", "first", "last", or a list of them'


def _the_format_is_registered(value: str | None) -> str | None:
    """A format is a name the export registry serves, refused with what it serves."""
    if value is None:
        return None
    return check_format_name(str(value))


def format_from_path(path: str | PurePath) -> str | None:
    """Return the name of the format a file extension names, or None."""
    return suffix_format(PurePath(path).suffix.lower())


def _iso_text(value: Any) -> Any:
    """Return a date or datetime as ISO text, anything else unchanged."""
    if isinstance(value, _dt.datetime):
        return value.isoformat(sep=" ") if value.time() != _dt.time() else value.date().isoformat()
    if isinstance(value, _dt.date):
        return value.isoformat()
    return value


def _parse_date(text: str) -> Any:
    """Return ``text`` as a timestamp, or raise ValueError when it is no date.

    The same reading as :mod:`hydromodpy.core.time.selection`: a date starts
    with a digit, so pandas never reads "now" or "today" as the wall clock.
    """
    import pandas as pd

    if not text[:1].isdigit():
        raise ValueError(text)
    try:
        instant = pd.Timestamp(text)
    except (ValueError, TypeError) as exc:
        raise ValueError(text) from exc
    if pd.isna(instant):
        raise ValueError(text)
    return instant


def _check_selector(value: Any) -> str | int:
    """Return one time selector checked for its shape: a date, a keyword or an index."""
    if isinstance(value, bool):
        raise ValueError(f"time = {value!r} is a boolean. Write {_TIME_HELP}.")
    if isinstance(value, int):
        return value
    if not isinstance(value, str):
        raise ValueError(f"time = {value!r} is not a time. Write {_TIME_HELP}.")
    word = value.strip().lower()
    if word == EXPORT_ALL:
        raise ValueError(
            'time = "all" is the default: leave time out to export the whole simulation.'
        )
    if word in _KEYWORDS:
        return word
    try:
        _parse_date(value)
    except ValueError:
        raise ValueError(f"time = {value!r} is not a date. Write {_TIME_HELP}.") from None
    return value


def selector_token(selector: str | int) -> str:
    """Return how a file name spells one time selector.

    A date is kept as written (``2001-08-15``), a keyword as the word, and a
    step index as ``step<i>``.
    """
    if isinstance(selector, int):
        return f"step{selector}"
    return str(selector).replace(" ", "T").replace(":", "")


class ExportRequest(HydroModelBase):
    """One export: what to write, when, in which format, where.

    Only ``variables`` is required. ``time`` names instants and ``period`` a
    window; without either the whole simulation is written. ``format`` is
    optional: each data goes to its natural format (a field at one date to
    GeoTIFF, over several dates to NetCDF, a series or a table to CSV, a vector
    layer to GeoPackage, a raster layer to GeoTIFF), and a ``file`` extension
    names the format too.
    """

    variables: Annotated[str | list[str], Profile.USER] = Field(
        description=(
            'What to export: a name, a list of names, or "all" for everything the run '
            "holds. One namespace covers the mesh fields (head, watertable_depth, "
            'seepage_mask..., and mesh_cell_area, which "all" leaves out because '
            "mesh_cells holds it), the series (discharge, discharge_obs...), the vector layers "
            "(watershed, hydrographic_network_reference...), the three layers of the cell "
            "mesh (mesh_cells, mesh_seeds, mesh_family_faces), the raster layers "
            "(watershed_dem...) and the table budget; 'hmp export <run> --list' prints what "
            "a run holds. A name no run can hold is refused before the solve."
        ),
        examples=["head", ["head", "discharge"], "all"],
    )
    time: Annotated[str | int | list[str | int] | None, Profile.USER] = Field(
        default=None,
        description=(
            'The instants to write: a date "YYYY-MM-DD", "first", "last", or a list of '
            "them. A date takes the stress period that holds it. A format that holds one "
            "instant (GeoTIFF, Shapefile, GeoPackage, VTU) writes one file per date. "
            "Left out, the whole simulation is written. Cannot be given with period."
        ),
    )
    period: Annotated[tuple[str, str] | None, Profile.USER] = Field(
        default=None,
        description=(
            'A window of the simulation, [start, end], two dates "YYYY-MM-DD". Every '
            "stress period it overlaps is written. Cannot be given with time."
        ),
    )
    format: Annotated[str | None, Profile.USER, AfterValidator(_the_format_is_registered)] = Field(
        default=None,
        description=(
            "The file format, a name the export registry serves. Left out, each data "
            "takes its natural format, or the one the extension of 'file' names. A "
            'view format describes the whole run and takes variables = "all" only. '
            "The portable archive of a run is written by 'hmp publish --container tar'."
        ),
        json_schema_extra=_the_format_help,
    )
    folder: Annotated[Path | None, Profile.USER] = Field(
        default=None,
        description=(
            "A folder under the exports/ directory of the run, where the files are written "
            "with automatic names. Relative to runs/<run>/exports/; an absolute folder or "
            "one that climbs out with '..' is refused. Left out, the files go to "
            "runs/<run>/exports/."
        ),
    )
    file: Annotated[Path | None, Profile.USER] = Field(
        default=None,
        description=(
            "One exact file to write; its extension gives the format. Relative to 'folder' "
            "under runs/<run>/exports/; an absolute file or one that climbs out with '..' "
            "is refused. Only for a request that writes one file: several files need "
            "'folder' and automatic names."
        ),
    )
    crs: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description=(
            "Output CRS, e.g. 'EPSG:4326'. Rasters and vector layers are reprojected "
            "from the model CRS. NetCDF, VTU and CSV do not reproject and refuse it. "
            "Left out, the model CRS is kept."
        ),
    )
    resolution: Annotated[float | None, Profile.USER] = Field(
        default=None,
        gt=0,
        description=(
            "Pixel size of a GeoTIFF of a field, in units of the output CRS. Left out, "
            "it is the side of the smallest cell of the mesh, and a mesh that would give "
            "more than 1e8 pixels is refused until a resolution is set. Refused on a "
            "request that writes no raster."
        ),
        json_schema_extra={"unit": "CRS unit"},
    )
    layer: Annotated[int | None, Profile.DEV] = Field(
        default=None,
        ge=0,
        description=(
            "Model layer of a 3D field, counted from 0 at the top. Left out, every layer a "
            "format can hold: a NetCDF variable or a VTU cell array has one entry per layer. "
            "QGIS reads a NetCDF that names one layer."
        ),
        json_schema_extra=field_metadata(unit="-"),
    )
    nodata: Annotated[float, Profile.EXPERT] = Field(
        default=-9999.0,
        description="Fill value of the cells a raster has no data for.",
    )
    deliver_to: Annotated[list[str] | None, Profile.USER] = Field(
        default=None,
        description=(
            "Where to send the files of this block once the run is sealed: a local or "
            "UNC folder ending with /, a file, or an ftp://, ftps:// or sftp:// address, "
            "whose identity comes from credentials.toml."
        ),
    )

    @model_validator(mode="before")
    @classmethod
    def _require_variables(cls, data: Any) -> Any:
        """Say what to write when ``variables`` is missing, not only that it is."""
        if isinstance(data, Mapping) and "variables" not in data:
            raise ValueError(
                'variables is missing: name what to export, e.g. variables = "head", '
                'variables = ["head", "discharge"], or variables = "all".'
            )
        return data

    @field_validator("format", mode="before")
    @classmethod
    def _refuse_retired_format(cls, value: Any) -> Any:
        """Name what replaces a format that is no longer written."""
        if isinstance(value, str) and value.strip().lower() in RETIRED_FORMATS:
            raise ValueError(RETIRED_FORMATS[value.strip().lower()])
        return value

    @field_validator("folder", "file")
    @classmethod
    def _inside_the_exports(cls, value: Path | None, info: Any) -> Path | None:
        """Keep every file under the exports directory of the run."""
        if value is None:
            return None
        if value.is_absolute() or PureWindowsPath(str(value)).is_absolute():
            raise ValueError(
                f"{info.field_name} = {value.as_posix()!r} is absolute. Exports are written "
                f"under runs/<run>/exports/: write a {info.field_name} relative to it, or "
                "copy the run out of the project with 'hmp publish <run> --to DEST'."
            )
        if ".." in value.parts:
            raise ValueError(
                f"{info.field_name} = {value.as_posix()!r} climbs out of runs/<run>/exports/ "
                "with '..'. Write a path inside it, or copy the run out of the project with "
                "'hmp publish <run> --to DEST'."
            )
        return value

    @field_validator("variables")
    @classmethod
    def _check_variables(cls, value: str | list[str]) -> str | list[str]:
        names = [value] if isinstance(value, str) else list(value)
        if not names or any(not name for name in names):
            raise ValueError(
                'variables is empty: name what to export, e.g. variables = "head", or '
                'variables = "all".'
            )
        if isinstance(value, list) and EXPORT_ALL in value:
            if len(value) == 1:
                return EXPORT_ALL
            raise ValueError(
                f'variables = {value!r} mixes "all" with names. Write variables = "all" '
                "alone, or list the names."
            )
        return value

    @field_validator(DELIVER_TO_KEY, mode="before")
    @classmethod
    def _one_as_a_list(cls, value: Any) -> Any:
        """Read a single destination as the list of one."""
        return [value] if isinstance(value, str) else value

    @field_validator(DELIVER_TO_KEY)
    @classmethod
    def _destinations(cls, value: list[str] | None) -> list[str] | None:
        """Refuse a destination no delivery reaches, with the phrase of its form."""
        if value is None:
            return None
        if not value:
            raise ValueError(
                "deliver_to is empty: name the folder, the file or the address to deliver "
                "to, or remove the key."
            )
        for text in value:
            parse_destination(text)
        return value

    @field_validator("time", mode="before")
    @classmethod
    def _dates_as_text(cls, value: Any) -> Any:
        """Read a bare TOML date as its ISO text, and refuse a boolean before it reads as 1."""
        items = list(value) if isinstance(value, list | tuple) else [value]
        for item in items:
            if isinstance(item, bool):
                raise ValueError(f"time = {item!r} is a boolean. Write {_TIME_HELP}.")
        if isinstance(value, list | tuple):
            return [_iso_text(item) for item in value]
        return _iso_text(value)

    @field_validator("time")
    @classmethod
    def _check_time(cls, value: str | int | list[str | int] | None) -> Any:
        if value is None:
            return None
        if isinstance(value, list):
            if not value:
                raise ValueError(
                    f"time = [] names no instant. Write {_TIME_HELP}, or leave time out "
                    "to export the whole simulation."
                )
            return [_check_selector(item) for item in value]
        return _check_selector(value)

    @field_validator("period", mode="before")
    @classmethod
    def _period_as_text(cls, value: Any) -> Any:
        if isinstance(value, list | tuple):
            return tuple(_iso_text(item) for item in value)
        return value

    @field_validator("period")
    @classmethod
    def _check_period(cls, value: tuple[str, str] | None) -> tuple[str, str] | None:
        if value is None:
            return None
        try:
            start, end = (_parse_date(item) for item in value)
        except ValueError:
            raise ValueError(
                f'period = {list(value)!r} is not two dates. Write period = ["YYYY-MM-DD", '
                '"YYYY-MM-DD"].'
            ) from None
        if start > end:
            raise ValueError(
                f"period = {list(value)!r} ends before it starts. Write the start first."
            )
        return value

    @model_validator(mode="after")
    def _check_request(self) -> ExportRequest:
        self._check_delivery()
        if self.time is not None and self.period is not None:
            raise ValueError(
                "time and period are both given. Write time for instants, or period for "
                "a window, not both."
            )
        fmt = self._resolve_format()
        if fmt in run_formats():
            self._check_run_format(fmt)
            return self
        if fmt in non_reprojecting_formats() and self.crs is not None:
            raise ValueError(
                f"crs = {self.crs!r} on format {fmt!r}, which does not reproject: "
                f"it is written in the model CRS. Drop crs, or write a GeoTIFF, a "
                "GeoPackage or a Shapefile."
            )
        if self.resolution is not None and fmt is not None and fmt != "geotiff":
            raise ValueError(
                f"resolution = {self.resolution!r} sizes the pixels of a GeoTIFF, and this "
                f'request writes {fmt}. Drop resolution, or write format = "geotiff".'
            )
        if self.file is not None:
            self._check_single_file(fmt)
        return self

    def _check_delivery(self) -> None:
        """Refuse a delivery this block cannot answer: a repeated target, no file, a view."""
        if not self.deliver_to:
            return
        destinations = [parse_destination(text) for text in self.deliver_to]
        seen: set[tuple[str, str | None, int | None, str, bool]] = set()
        for text, destination in zip(self.deliver_to, destinations, strict=True):
            key = (
                destination.scheme,
                destination.host,
                destination.port,
                destination.path,
                destination.folder,
            )
            if key in seen:
                raise ValueError(f"deliver_to names {text!r} twice.")
            seen.add(key)
        if (
            self.folder is None
            and self.file is None
            and self.output_format is not None
            and self.output_format in run_formats()
        ):
            raise ValueError(
                "a view is delivered from exports/: give this block folder or file, or "
                "remove deliver_to."
            )
        files = [destination for destination in destinations if not destination.folder]
        if files and self.file is None:
            raise ValueError(
                f"deliver_to = {files[0].text!r} names one remote file, so the block must "
                'write one file with file = "...". End the address with / to deliver into '
                "a folder."
            )

    def _resolve_format(self) -> str | None:
        """Return the declared format, checked against the extension of ``file``."""
        if self.file is None:
            return self.format
        named = format_from_path(self.file)
        if self.format is None:
            if named is None:
                known = ", ".join(known_extensions())
                raise ValueError(
                    f"file = {self.file.as_posix()!r} has no extension a format is known by "
                    f"({known}). Give it one, or write format."
                )
            return named
        if named is not None and named != self.format:
            raise ValueError(
                f"format = {self.format!r} and file = {self.file.as_posix()!r}, which "
                f"names a {named} file. Drop format to take the extension, or give the file "
                f"the extension {format_suffix(self.format)}."
            )
        return self.format

    def _check_run_format(self, fmt: str) -> None:
        """A run format describes the whole run: every selector is refused."""
        if self.variables != EXPORT_ALL:
            raise ValueError(
                f"format = {fmt!r} describes the whole run, not a variable. Write "
                f'variables = "all".'
            )
        given = [
            key
            for key in ("time", "period", "crs", "resolution", "layer")
            if getattr(self, key) is not None
        ]
        if given:
            raise ValueError(
                f"format = {fmt!r} writes the whole run, so {', '.join(given)} "
                f"{'selects' if len(given) == 1 else 'select'} nothing. Drop "
                f"{'it' if len(given) == 1 else 'them'}."
            )

    def _check_single_file(self, fmt: str | None) -> None:
        """Refuse a ``file`` on a request that writes several files, when that is certain."""
        if fmt not in one_instant_formats():
            return
        reasons: list[str] = []
        if self.variables == EXPORT_ALL:
            reasons.append('variables = "all" writes one file per name')
        elif (count := _count_files(self.names, fmt)) > 1:
            n_names = len(self.names)
            reasons.append(
                f"{n_names} names write one file each"
                if count == n_names
                else f"{n_names} names write {count} files"
            )
        if len(self.times) > 1:
            reasons.append(f"{len(self.times)} dates write one file each")
        if reasons:
            raise ValueError(
                f"file = {self.file.as_posix()!r} names one file, but in {fmt} "
                f"{' and '.join(reasons)}. Write folder instead of file, or format = "
                '"netcdf", which holds several variables and dates in one file.'
            )

    @property
    def exports_all(self) -> bool:
        """True when the request asks for everything the run holds."""
        return self.variables == EXPORT_ALL

    @property
    def names(self) -> list[str]:
        """The names the request lists, empty when it asks for ``"all"``."""
        if self.exports_all:
            return []
        return [self.variables] if isinstance(self.variables, str) else list(self.variables)

    @property
    def times(self) -> list[str | int]:
        """The instants the request names, empty when it names none."""
        if self.time is None:
            return []
        return list(self.time) if isinstance(self.time, list) else [self.time]

    @property
    def output_format(self) -> str | None:
        """The format the request declares, directly or by the extension of ``file``."""
        if self.format is not None:
            return self.format
        return None if self.file is None else format_from_path(self.file)


@dataclass(frozen=True, slots=True)
class PlannedFile:
    """One file an export request writes.

    ``path`` is relative to the ``exports/`` directory of the run. It is spelled with forward slashes on every OS, as a TOML writes
    it: the config check compares and reports it, and the exporter turns it
    into a native path only to write the file. It holds
    :data:`STEP_DATE_TOKEN` when one file is written per step and the steps
    are known only on the run. ``instant`` is the time selector of a
    one-instant file, None otherwise.
    """

    path: PurePosixPath
    format: str
    variables: tuple[str, ...]
    instant: str | int | None = None

    @property
    def per_step(self) -> bool:
        """True when the file is written once per step of the selection."""
        return STEP_DATE_TOKEN in self.path.name


def _natural_format(kind: ExportKind, request: ExportRequest) -> str:
    """Return the format a kind of data takes when the request names none."""
    if kind is ExportKind.field:
        return "geotiff" if len(request.times) == 1 else kind_formats(kind)[0]
    return kind_formats(kind)[0]


def _count_files(names: Sequence[str], fmt: str) -> int:
    """Return how many files ``names`` write in a one-instant format, one each at most."""
    mesh = sum(name in MESH_LAYERS for name in names)
    if fmt == "geopackage" and mesh:
        return len(names) - mesh + 1
    return len(names)


def _files_of_names(
    kind: ExportKind, fmt: str, names: Sequence[str], run_label: str
) -> list[tuple[str, tuple[str, ...]]]:
    """Return the ``(stem, names)`` of each file that holds names of one kind.

    One file per name, except the mesh layers of a GeoPackage: they are one
    file, named after the layer when there is one and after the run when there
    are several. A Shapefile holds a single layer, so it keeps a file each.
    """
    mesh = [name for name in names if name in MESH_LAYERS]
    if kind is not ExportKind.vector or fmt != "geopackage" or not mesh:
        return [(name, (name,)) for name in names]
    files = [(name, (name,)) for name in names if name not in MESH_LAYERS]
    files.append((mesh[0] if len(mesh) == 1 else f"{run_label}_mesh", tuple(mesh)))
    return files


def _posix(path: PurePath) -> PurePosixPath:
    """Return a path of the request spelled as a TOML writes it, whatever the OS."""
    return PurePosixPath(path.as_posix())


def _span_token(request: ExportRequest) -> str:
    """Return the time part of a name for a file holding the whole selection."""
    if request.period is not None:
        start, end = request.period
        return f"_{selector_token(start)}_{selector_token(end)}"
    if len(request.times) == 1:
        return f"_{selector_token(request.times[0])}"
    return ""


def plan_outputs(
    request: ExportRequest,
    kinds: Mapping[str, ExportKind | str],
    *,
    run_label: str,
    names: Sequence[str] | None = None,
) -> tuple[PlannedFile, ...]:
    """Return every file ``request`` writes, named, in the order it writes them.

    Parameters
    ----------
    request
        The export request.
    kinds
        The kind of every name the request exports.
    run_label
        The name of the run: the stem of a file that holds several variables.
    names
        What ``variables = "all"`` stands for on this run. Ignored for a
        request that lists its names. Without it, a data request for "all"
        plans nothing: the run decides what it holds.

    Raises
    ------
    ValueError
        A kind the requested format cannot hold, a ``crs`` or a
        ``resolution`` no planned file can carry, or a ``file`` on a request
        that writes several files.
    """
    native = request.folder if request.folder is not None else PurePath()
    folder = _posix(native)
    file = None if request.file is None else _posix(native / request.file)
    fmt = request.output_format
    views = run_formats()
    if fmt is not None and fmt in views:
        if fmt not in VIEW_FILENAMES:
            raise ValueError(
                f"format = {fmt!r} describes the whole run, and the storage contract "
                f"names no file for it. A view format is one of {', '.join(sorted(views))}."
            )
        path = file if file is not None else folder / view_filename(fmt)
        return (PlannedFile(path=path, format=fmt, variables=()),)

    selected = request.names if not request.exports_all else list(names or ())
    by_kind: dict[ExportKind, list[str]] = {}
    for name in selected:
        kind = ExportKind(kinds[name])
        if fmt is not None and fmt not in kind_formats(kind):
            if request.exports_all:
                continue
            accepted = ", ".join(kind_formats(kind))
            raise ValueError(
                f"{name!r} is a {kind.value}, which cannot be written as {fmt}. "
                f"A {kind.value} is written as {accepted}."
            )
        by_kind.setdefault(kind, []).append(name)

    planned: list[PlannedFile] = []
    span = _span_token(request)
    one_instant = one_instant_formats()
    for kind, kind_names in by_kind.items():
        out = fmt or _natural_format(kind, request)
        suffix = format_suffix(out)
        if kind is ExportKind.field and out in one_instant:
            instants: list[str | int | None] = list(request.times) or [None]
            for name in kind_names:
                for instant in instants:
                    token = STEP_DATE_TOKEN if instant is None else selector_token(instant)
                    planned.append(
                        PlannedFile(
                            path=folder / f"{name}_{token}{suffix}",
                            format=out,
                            variables=(name,),
                            instant=instant,
                        )
                    )
        elif kind in (ExportKind.field, ExportKind.series):
            stem = kind_names[0] if len(kind_names) == 1 else f"{run_label}_{_GROUP_STEM[kind]}"
            planned.append(
                PlannedFile(
                    path=folder / f"{stem}{span}{suffix}", format=out, variables=tuple(kind_names)
                )
            )
        else:
            token = span if kind is ExportKind.table else ""
            files = _files_of_names(kind, out, kind_names, run_label)
            planned.extend(
                PlannedFile(path=folder / f"{stem}{token}{suffix}", format=out, variables=group)
                for stem, group in files
            )

    _check_plan(request, planned)
    if file is not None and planned:
        only = planned[0]
        return (
            PlannedFile(
                path=file,
                format=only.format,
                variables=only.variables,
                instant=only.instant,
            ),
        )
    return tuple(planned)


def _check_plan(request: ExportRequest, planned: list[PlannedFile]) -> None:
    """Refuse the keys no planned file can honor, and a file that is several."""
    formats = {item.format for item in planned}
    flat = formats & non_reprojecting_formats()
    # "all" takes each data in its format, so crs reprojects the ones that can be.
    # A named list is a choice: a name crs would not reach is refused.
    refused = flat == formats if request.exports_all else bool(flat)
    if request.crs is not None and formats and refused:
        written = ", ".join(sorted(flat))
        raise ValueError(
            f"crs = {request.crs!r}, but this request writes {written}, which does not "
            "reproject. Drop crs, or ask for a GeoTIFF, a GeoPackage or a Shapefile."
        )
    if request.resolution is not None and formats and "geotiff" not in formats:
        raise ValueError(
            f"resolution = {request.resolution!r} sizes the pixels of a GeoTIFF, and this "
            "request writes none. Drop resolution, or write one date of a field."
        )
    if request.file is None:
        return
    if len(planned) > 1 or any(item.per_step for item in planned):
        count = "one file per date" if len(planned) == 1 else f"{len(planned)} files"
        raise ValueError(
            f"file = {request.file.as_posix()!r} names one file, but this request writes "
            f"{count}. Write folder instead of file, or split the request in blocks of "
            "one file each."
        )


_EXPORT_REQUESTS: TypeAdapter[list[ExportRequest]] = TypeAdapter(list[ExportRequest])


def load_export_requests(data: Any) -> list[ExportRequest]:
    """Validate the ``[[export]]`` blocks of a document, in the order of the file.

    A refusal carries the index of its block, which the config loader renders
    as ``export[2]``. A table ``[export]`` is refused: a request is a block of
    the array ``[[export]]``.
    """
    if data is None:
        return []
    if isinstance(data, Mapping):
        told = (
            "[export] is written as a table. An export is a request, one block per "
            'request: write [[export]] with variables = "...", and one block more for '
            "each other export."
        )
        if data:
            told += " " + prerelease_refusal("[export]", [str(key) for key in data])
        raise ValueError(told)
    return _EXPORT_REQUESTS.validate_python(list(data))


__all__ = [
    "EXPORT_ALL",
    "MESH_LAYERS",
    "RETIRED_FORMATS",
    "STEP_DATE_TOKEN",
    "ExportKind",
    "ExportRequest",
    "PlannedFile",
    "format_from_path",
    "load_export_requests",
    "plan_outputs",
    "selector_token",
]
