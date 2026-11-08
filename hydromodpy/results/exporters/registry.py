"""The export registry: every format a document can ask an export to write.

One instance of the common registry engine holds them,
:data:`export_formats`, keyed on the one attribute every format declares:
``name``. Seven formats ship in this wheel, six file formats and the RO-Crate
view; a format outside the wheel joins through the
``hydromodpy.export.format`` entry-point group, named after its format.

Nothing here is written by hand twice. The tables the rest of the package
planned files with, the suffix of a format, the formats a kind of data goes
to, the formats that hold one instant per file, the views, are derived from
the declarations every format carries, so a format added anywhere is served
everywhere on the same lines.
"""

from __future__ import annotations

from pathlib import Path

from hydromodpy.core.exceptions import ExportError
from hydromodpy.core.plugin_registry import PluginRegistry, check_registered_name
from hydromodpy.results.exporters.port import EXPORT_WRITER_MEMBERS
from hydromodpy.schema.generated_views import VIEW_FILENAMES

EXPORT_FORMAT_GROUP = "hydromodpy.export.format"
"""The entry-point group an out-of-tree export format joins the registry in."""

_BUILTIN_PATHS: dict[str, str] = {
    "netcdf": "hydromodpy.results.exporters.formats:NetcdfFormat",
    "geotiff": "hydromodpy.results.exporters.formats:GeotiffFormat",
    "csv": "hydromodpy.results.exporters.formats:CsvFormat",
    "geopackage": "hydromodpy.results.exporters.formats:GeopackageFormat",
    "shapefile": "hydromodpy.results.exporters.formats:ShapefileFormat",
    "vtu": "hydromodpy.results.exporters.formats:VtuFormat",
    "rocrate": "hydromodpy.results.export.rocrate:RoCrateView",
}
"""The formats this build ships. The order is the one the derived tables name
them in."""

_LONG_SPELLINGS: dict[str, str] = {".tif": ".tiff"}
"""The long spelling of an extension a request may also write it with."""

export_formats = PluginRegistry(
    kind="export format",
    id_attributes=("name",),
    group=EXPORT_FORMAT_GROUP,
    builtin_paths=_BUILTIN_PATHS,
    members=lambda: EXPORT_WRITER_MEMBERS,
    error=ExportError,
)
"""Resolve the name a document writes to the format class that serves it."""


def check_format_name(value: str) -> str:
    """Return *value* when an export format serves it, else refuse it.

    The refusal goes through the registry, not a plain name list, because the
    registry also knows the formats an entry point declares that this process
    cannot import: those are refused with their target and the reason.

    Raises
    ------
    ValueError
        When *value* is served by no format. Pydantic places it on the field
        being read.
    """
    served = export_formats.names()
    try:
        return check_registered_name(value, served, key="export.format", group=EXPORT_FORMAT_GROUP)
    except ValueError:
        unavailable = export_formats.unavailable.get(value)
        if unavailable is not None:
            raise ValueError(unavailable) from None
        raise


def _declaration_order() -> list[str]:
    """The served names, the shipped ones in their declared order, then the rest."""
    if not export_formats.plugins_loaded:
        export_formats.load_plugins()
    return [*dict.fromkeys((*export_formats.builtin_paths, *export_formats.names()))]


def _classes() -> list[tuple[str, type]]:
    """The served format classes, in declaration order."""
    return [(name, export_formats.get(name)) for name in _declaration_order()]


_RUN_WRITES = frozenset({"run"})
"""The one ``writes`` a format that describes the whole run declares."""


def run_formats() -> frozenset[str]:
    """The formats that describe the whole run, never a variable."""
    return frozenset(
        name
        for name, cls in _classes()
        if _RUN_WRITES.issubset(cls.writes) and name in VIEW_FILENAMES
    )


def view_filename(name: str) -> str:
    """The file name a view of format *name* takes inside a sealed directory."""
    return VIEW_FILENAMES[name]


def format_suffix(name: str) -> str:
    """The extension of the files the format *name* writes."""
    return str(export_formats.get(name).suffix)


def suffix_format(suffix: str) -> str | None:
    """The format an input file extension names, or ``None``.

    An extension two formats share names neither: both view files the
    storage contract fixes end in ``.json``, so ``.json`` names no format,
    while ``.jsonld`` names the PROV view. ``.tiff`` names GeoTIFF.
    """
    return _unique_extension_table().get(suffix.lower())


def _unique_extension_table() -> dict[str, str]:
    """The extensions that name one format, and only those."""
    claims: dict[str, list[str]] = {}
    for extension, name in _extension_claims():
        claims.setdefault(extension, []).append(name)
    return {extension: names[0] for extension, names in claims.items() if len(names) == 1}


def _extension_claims() -> list[tuple[str, str]]:
    """Every ``(extension, format)`` a request can be named by, dots included.

    A data format claims the suffix it writes, and its long spelling. A view
    claims the extension of the file the storage contract fixes for it, the
    one name it always takes, whether or not this process can load the
    format: the file name is a fact of the layout, written in the schema.
    """
    claims: list[tuple[str, str]] = []
    for name, cls in _classes():
        if _RUN_WRITES.issubset(cls.writes):
            continue
        claims.append((str(cls.suffix), name))
        claims.extend((long, name) for long in _long_spellings_of(cls))
    claims.extend((Path(filename).suffix, name) for name, filename in VIEW_FILENAMES.items())
    return claims


def _long_spellings_of(cls: type) -> tuple[str, ...]:
    """The long spellings of the extension of *cls* a request may also write."""
    suffix = str(cls.suffix)
    return tuple(long for short, long in _LONG_SPELLINGS.items() if suffix == short)


def known_extensions() -> tuple[str, ...]:
    """Every extension a request can name a format with, sorted."""
    return tuple(sorted(_unique_extension_table()))


def one_instant_formats() -> frozenset[str]:
    """The formats that hold one instant of a field per file."""
    return frozenset(
        name for name, cls in _classes() if cls.instants == "one" and "run" not in cls.writes
    )


def non_reprojecting_formats() -> frozenset[str]:
    """The formats written in the model CRS only."""
    return frozenset(
        name for name, cls in _classes() if not cls.reprojects and "run" not in cls.writes
    )


def kind_formats(kind: str) -> tuple[str, ...]:
    """The formats a kind of data can be written in, its natural ones first."""
    classes = _classes()
    natural = tuple(
        name for name, cls in classes if "run" not in cls.writes and kind in cls.natural
    )
    others = tuple(
        name
        for name, cls in classes
        if "run" not in cls.writes and kind in cls.writes and name not in natural
    )
    return natural + others


def format_help(name: str) -> str:
    """The one-sentence description of a format, for the config schema."""
    return str(export_formats.get(name).help)


__all__ = [
    "EXPORT_FORMAT_GROUP",
    "check_format_name",
    "export_formats",
    "format_help",
    "format_suffix",
    "kind_formats",
    "known_extensions",
    "non_reprojecting_formats",
    "one_instant_formats",
    "run_formats",
    "suffix_format",
    "view_filename",
]
