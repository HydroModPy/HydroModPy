"""One export request: what to export, when, in which format, where.

A TOML ``[[export]]`` block, a ``run.export(...)`` call and ``hmp export``
build the same :class:`ExportRequest`, so the words and the refusals are the
same on the three surfaces. Only ``variables`` is required. The other keys say
when (``time`` or ``period``), in which format (``format``, or the extension of
``file``) and where (``folder``, ``file``). Left out, each takes the natural
answer: the whole simulation, the natural format of each data, and
``share/<run>/``.

The model refuses what it can decide alone, without the run and without the
kind of each name. :func:`plan_outputs` finishes the job once the kind of each
name is known: it names every file a request writes and refuses what the kinds
make impossible (a vector layer in a NetCDF, a reprojection a format cannot
carry). The step 0 check and the exporters both call it, so the plan checked
before the solve is the plan written after it.

Lives in ``core.config_kit`` because ``config``, ``results`` and ``workflow``
all build it, and ``core`` is the only layer they may all import.
"""

from __future__ import annotations

import datetime as _dt
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path, PurePath
from typing import Annotated, Any

from pydantic import Field, TypeAdapter, field_validator, model_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile

EXPORT_ALL = "all"
"""The ``variables`` value that asks for everything a run holds."""

STEP_DATE_TOKEN = "{date}"
"""Placeholder in a planned file name, filled with the date of each step written."""


class ExportFormat(StrEnum):
    """What an export writes."""

    netcdf = "netcdf"
    geotiff = "geotiff"
    csv = "csv"
    geopackage = "geopackage"
    shapefile = "shapefile"
    vtu = "vtu"
    package = "package"
    stac = "stac"
    rocrate = "rocrate"
    prov = "prov"


class ExportKind(StrEnum):
    """What a name a user can export is."""

    field = "field"
    series = "series"
    table = "table"
    vector = "vector"
    raster = "raster"


# File extension -> format. The one place an extension is read.
_SUFFIX_TO_FORMAT: dict[str, ExportFormat] = {
    ".nc": ExportFormat.netcdf,
    ".tif": ExportFormat.geotiff,
    ".tiff": ExportFormat.geotiff,
    ".csv": ExportFormat.csv,
    ".gpkg": ExportFormat.geopackage,
    ".shp": ExportFormat.shapefile,
    ".vtu": ExportFormat.vtu,
    ".hmp": ExportFormat.package,
    ".jsonld": ExportFormat.prov,
}

FORMAT_SUFFIX: dict[ExportFormat, str] = {
    ExportFormat.netcdf: ".nc",
    ExportFormat.geotiff: ".tif",
    ExportFormat.csv: ".csv",
    ExportFormat.geopackage: ".gpkg",
    ExportFormat.shapefile: ".shp",
    ExportFormat.vtu: ".vtu",
    ExportFormat.package: ".hmp",
}
"""The extension of the files a data format writes."""

SINGLE_INSTANT_FORMATS = frozenset(
    {ExportFormat.geotiff, ExportFormat.shapefile, ExportFormat.geopackage, ExportFormat.vtu}
)
"""Formats holding one instant of a field per file: several dates write one file per date."""

RUN_FORMATS = frozenset(
    {ExportFormat.package, ExportFormat.stac, ExportFormat.rocrate, ExportFormat.prov}
)
"""Formats that describe the whole run, not a variable: they take ``variables = "all"``."""

NON_REPROJECTING_FORMATS = frozenset({ExportFormat.netcdf, ExportFormat.vtu, ExportFormat.csv})
"""Formats written in the model CRS only: ``crs`` is refused on them."""

KIND_FORMATS: dict[ExportKind, tuple[ExportFormat, ...]] = {
    ExportKind.field: (
        ExportFormat.netcdf,
        ExportFormat.geotiff,
        ExportFormat.geopackage,
        ExportFormat.shapefile,
        ExportFormat.vtu,
    ),
    ExportKind.series: (ExportFormat.csv,),
    ExportKind.table: (ExportFormat.csv,),
    ExportKind.vector: (ExportFormat.geopackage, ExportFormat.shapefile),
    ExportKind.raster: (ExportFormat.geotiff,),
}
"""The formats each kind of data can be written in. The first one is its natural format."""

_RUN_FORMAT_FILES: dict[ExportFormat, str] = {
    ExportFormat.stac: "stac-item.json",
    ExportFormat.rocrate: "ro-crate-metadata.json",
    ExportFormat.prov: "prov.jsonld",
}

# The stem of a file that holds several names of one kind.
_GROUP_STEM: dict[ExportKind, str] = {ExportKind.field: "fields", ExportKind.series: "series"}

_KEYWORDS = ("first", "last")
_TIME_HELP = 'a date "YYYY-MM-DD", "first", "last", or a list of them'


def format_from_path(path: str | PurePath) -> ExportFormat | None:
    """Return the format a file extension names, or None."""
    return _SUFFIX_TO_FORMAT.get(PurePath(path).suffix.lower())


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
            "seepage_mask...), the series (discharge, discharge_obs...), the vector layers "
            "(watershed, hydrographic_network_reference...), the raster layers "
            "(watershed_dem...) and the table budget; 'hmp export <run> --list' prints what "
            "a run holds. A name no run can hold is refused before the solve."
        ),
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
    format: Annotated[ExportFormat | None, Profile.USER] = Field(
        default=None,
        description=(
            "The file format. Left out, each data takes its natural format, or the one "
            "the extension of 'file' names. 'package' writes the portable .hmp archive "
            "of the run; 'stac', 'rocrate' and 'prov' write its metadata. Those four "
            'describe the whole run and take variables = "all" only.'
        ),
    )
    folder: Annotated[Path | None, Profile.USER] = Field(
        default=None,
        description=(
            "The folder the files are written to, with automatic names. A relative "
            "folder is read from the project's share/ directory. Defaults to "
            "share/<run>/."
        ),
    )
    file: Annotated[Path | None, Profile.USER] = Field(
        default=None,
        description=(
            "One exact file to write; its extension gives the format. A relative file "
            "is read from 'folder'. Only for a request that writes one file: several "
            "files need 'folder' and automatic names."
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
            "Pixel size of a GeoTIFF of a field, in units of the output CRS. Derived "
            "from the mesh when left out. Refused on a request that writes no raster."
        ),
    )
    layer: Annotated[int | None, Profile.DEV] = Field(
        default=None,
        ge=0,
        description="Model layer of a 3D field. Left out, every layer a format can hold.",
    )
    nodata: Annotated[float, Profile.EXPERT] = Field(
        default=-9999.0,
        description="Fill value of the cells a raster has no data for.",
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
        if self.time is not None and self.period is not None:
            raise ValueError(
                "time and period are both given. Write time for instants, or period for "
                "a window, not both."
            )
        fmt = self._resolve_format()
        if fmt in RUN_FORMATS:
            self._check_run_format(fmt)
            return self
        if fmt in NON_REPROJECTING_FORMATS and self.crs is not None:
            raise ValueError(
                f"crs = {self.crs!r} on format {fmt.value!r}, which does not reproject: "
                f"it is written in the model CRS. Drop crs, or write a GeoTIFF, a "
                "GeoPackage or a Shapefile."
            )
        if self.resolution is not None and fmt is not None and fmt is not ExportFormat.geotiff:
            raise ValueError(
                f"resolution = {self.resolution!r} sizes the pixels of a GeoTIFF, and this "
                f'request writes {fmt.value}. Drop resolution, or write format = "geotiff".'
            )
        if self.file is not None:
            self._check_single_file(fmt)
        return self

    def _resolve_format(self) -> ExportFormat | None:
        """Return the declared format, checked against the extension of ``file``."""
        if self.file is None:
            return self.format
        named = format_from_path(self.file)
        if self.format is None:
            if named is None:
                known = ", ".join(sorted(_SUFFIX_TO_FORMAT))
                raise ValueError(
                    f"file = {str(self.file)!r} has no extension a format is known by "
                    f"({known}). Give it one, or write format."
                )
            return named
        if named is not None and named is not self.format:
            raise ValueError(
                f"format = {self.format.value!r} and file = {str(self.file)!r}, which names "
                f"a {named.value} file. Drop format to take the extension, or give the file "
                f"the extension {FORMAT_SUFFIX.get(self.format, 'of the format')}."
            )
        return self.format

    def _check_run_format(self, fmt: ExportFormat) -> None:
        """A run format describes the whole run: every selector is refused."""
        if self.variables != EXPORT_ALL:
            raise ValueError(
                f"format = {fmt.value!r} describes the whole run, not a variable. Write "
                f'variables = "all".'
            )
        given = [
            key
            for key in ("time", "period", "crs", "resolution", "layer")
            if getattr(self, key) is not None
        ]
        if given:
            raise ValueError(
                f"format = {fmt.value!r} writes the whole run, so {', '.join(given)} "
                f"{'selects' if len(given) == 1 else 'select'} nothing. Drop "
                f"{'it' if len(given) == 1 else 'them'}."
            )

    def _check_single_file(self, fmt: ExportFormat | None) -> None:
        """Refuse a ``file`` on a request that writes several files, when that is certain."""
        if fmt not in SINGLE_INSTANT_FORMATS:
            return
        reasons: list[str] = []
        if self.variables == EXPORT_ALL:
            reasons.append('variables = "all" writes one file per name')
        elif len(self.names) > 1:
            reasons.append(f"{len(self.names)} names write one file each")
        if len(self.times) > 1:
            reasons.append(f"{len(self.times)} dates write one file each")
        if reasons:
            raise ValueError(
                f"file = {str(self.file)!r} names one file, but in {fmt.value} "
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
    def output_format(self) -> ExportFormat | None:
        """The format the request declares, directly or by the extension of ``file``."""
        if self.format is not None:
            return self.format
        return None if self.file is None else format_from_path(self.file)


@dataclass(frozen=True, slots=True)
class PlannedFile:
    """One file an export request writes.

    ``path`` is relative to ``share/`` when the request names no absolute
    folder. It holds :data:`STEP_DATE_TOKEN` when one file is written per step
    and the steps are known only on the run. ``instant`` is the time selector
    of a one-instant file, None otherwise.
    """

    path: PurePath
    format: ExportFormat
    variables: tuple[str, ...]
    instant: str | int | None = None

    @property
    def per_step(self) -> bool:
        """True when the file is written once per step of the selection."""
        return STEP_DATE_TOKEN in self.path.name


def _natural_format(kind: ExportKind, request: ExportRequest) -> ExportFormat:
    """Return the format a kind of data takes when the request names none."""
    if kind is ExportKind.field:
        return ExportFormat.geotiff if len(request.times) == 1 else ExportFormat.netcdf
    return KIND_FORMATS[kind][0]


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
        The name of the run, the default folder and the stem of a file that
        holds several variables.
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
    folder = PurePath(request.folder) if request.folder is not None else PurePath(run_label)
    fmt = request.output_format
    if fmt in RUN_FORMATS:
        default = _RUN_FORMAT_FILES.get(fmt, f"{run_label}{FORMAT_SUFFIX.get(fmt, '')}")
        name = request.file if request.file is not None else PurePath(default)
        return (PlannedFile(path=folder / name, format=fmt, variables=()),)

    selected = request.names if not request.exports_all else list(names or ())
    by_kind: dict[ExportKind, list[str]] = {}
    for name in selected:
        kind = ExportKind(kinds[name])
        if fmt is not None and fmt not in KIND_FORMATS[kind]:
            if request.exports_all:
                continue
            accepted = ", ".join(item.value for item in KIND_FORMATS[kind])
            raise ValueError(
                f"{name!r} is a {kind.value}, which cannot be written as {fmt.value}. "
                f"A {kind.value} is written as {accepted}."
            )
        by_kind.setdefault(kind, []).append(name)

    planned: list[PlannedFile] = []
    span = _span_token(request)
    for kind, kind_names in by_kind.items():
        out = fmt or _natural_format(kind, request)
        suffix = FORMAT_SUFFIX[out]
        if kind is ExportKind.field and out in SINGLE_INSTANT_FORMATS:
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
            planned.extend(
                PlannedFile(path=folder / f"{name}{token}{suffix}", format=out, variables=(name,))
                for name in kind_names
            )

    _check_plan(request, planned)
    if request.file is not None and planned:
        only = planned[0]
        return (
            PlannedFile(
                path=folder / request.file,
                format=only.format,
                variables=only.variables,
                instant=only.instant,
            ),
        )
    return tuple(planned)


def _check_plan(request: ExportRequest, planned: list[PlannedFile]) -> None:
    """Refuse the keys no planned file can honour, and a file that is several."""
    formats = {item.format for item in planned}
    flat = formats & NON_REPROJECTING_FORMATS
    # "all" takes each data in its format, so crs reprojects the ones that can be.
    # A named list is a choice: a name crs would not reach is refused.
    refused = flat == formats if request.exports_all else bool(flat)
    if request.crs is not None and formats and refused:
        written = ", ".join(sorted(item.value for item in flat))
        raise ValueError(
            f"crs = {request.crs!r}, but this request writes {written}, which does not "
            "reproject. Drop crs, or ask for a GeoTIFF, a GeoPackage or a Shapefile."
        )
    if request.resolution is not None and formats and ExportFormat.geotiff not in formats:
        raise ValueError(
            f"resolution = {request.resolution!r} sizes the pixels of a GeoTIFF, and this "
            "request writes none. Drop resolution, or write one date of a field."
        )
    if request.file is None:
        return
    if len(planned) > 1 or any(item.per_step for item in planned):
        count = "one file per date" if len(planned) == 1 else f"{len(planned)} files"
        raise ValueError(
            f"file = {str(request.file)!r} names one file, but this request writes "
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
        raise ValueError(
            "[export] is written as a table. An export is a request, one block per "
            'request: write [[export]] with variables = "...", and one block more for '
            "each other export. 'hmp doctor --fix-config' rewrites a file written for "
            "the old [export] toggles."
        )
    return _EXPORT_REQUESTS.validate_python(list(data))


__all__ = [
    "EXPORT_ALL",
    "FORMAT_SUFFIX",
    "KIND_FORMATS",
    "NON_REPROJECTING_FORMATS",
    "RUN_FORMATS",
    "SINGLE_INSTANT_FORMATS",
    "STEP_DATE_TOKEN",
    "ExportFormat",
    "ExportKind",
    "ExportRequest",
    "PlannedFile",
    "format_from_path",
    "load_export_requests",
    "plan_outputs",
    "selector_token",
]
