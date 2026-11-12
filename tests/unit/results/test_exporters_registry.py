"""The export registry serves what its formats declare, and only that.

The registry is the one vocabulary of the [[export]] format key and of
``--as``. The tables below are written as the literals of the commit this lot
started from, so the derivation is held against the shapes it replaces. The
refusals are the other half: an unknown name names the formats this
installation serves, and a format an entry point declares that this process
cannot import is refused with its target and the reason.
"""

from __future__ import annotations

import pytest

import hydromodpy.core.plugin_registry as plugin_registry
from hydromodpy.core.exceptions import ExportError
from hydromodpy.results.exporters.export_spec import ExportKind
from hydromodpy.results.exporters.registry import export_formats, known_extensions

pytestmark = pytest.mark.fast

# The tables of the commit this lot started from, spelled in literals so the
# derivation is held against what it replaces.
_KIND_FORMATS = {
    ExportKind.field: ("netcdf", "geotiff", "geopackage", "shapefile", "vtu"),
    ExportKind.series: ("csv",),
    ExportKind.table: ("csv",),
    ExportKind.vector: ("geopackage", "shapefile"),
    ExportKind.raster: ("geotiff",),
}

_FORMAT_SUFFIX = {
    "netcdf": ".nc",
    "geotiff": ".tif",
    "csv": ".csv",
    "geopackage": ".gpkg",
    "shapefile": ".shp",
    "vtu": ".vtu",
}

_SUFFIX_TO_FORMAT = {
    ".nc": "netcdf",
    ".tif": "geotiff",
    ".tiff": "geotiff",
    ".csv": "csv",
    ".gpkg": "geopackage",
    ".shp": "shapefile",
    ".vtu": "vtu",
    ".jsonld": "prov",
}

_RUN_FORMAT_FILES = {
    "stac": "stac-item.json",
    "rocrate": "ro-crate-metadata.json",
    "prov": "prov.jsonld",
}


def test_known_extensions() -> None:
    assert known_extensions() == tuple(sorted(_SUFFIX_TO_FORMAT))


class _FailingEntryPoint:
    """The entry point of the annex, on an installation where it cannot load."""

    name = "stac"
    value = "hydromodpy_annex.export.stac:StacItemView"

    def load(self):
        raise ModuleNotFoundError("No module named 'hydromodpy_annex'")


def test_unimportable_format_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The refusal names the module to put on sys.path, and the name is served nowhere."""
    monkeypatch.setattr(
        plugin_registry,
        "entry_points",
        lambda group: [_FailingEntryPoint()] if group == "hydromodpy.export.format" else [],
    )
    monkeypatch.setattr(export_formats, "unavailable", {})
    monkeypatch.setattr(export_formats, "classes", dict(export_formats.classes))
    monkeypatch.setattr(export_formats, "plugins_loaded", False)

    assert "stac" not in export_formats.names()
    with pytest.raises(ExportError) as raised:
        export_formats.get("stac")
    message = str(raised.value)
    assert (
        "'stac' is declared by the entry point stac = hydromodpy_annex.export.stac:StacItemView"
        in message
    )
    assert "No module named 'hydromodpy_annex'" in message
    assert "Put the package that provides it on sys.path." in message
