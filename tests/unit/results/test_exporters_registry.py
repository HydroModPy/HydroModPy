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
from hydromodpy.results.exporters.registry import (
    check_format_name,
    export_formats,
    format_suffix,
    kind_formats,
    known_extensions,
    non_reprojecting_formats,
    one_instant_formats,
    run_formats,
    suffix_format,
    view_filename,
)

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


@pytest.mark.parametrize("kind", list(ExportKind))
def test_the_formats_of_a_kind_are_derived_as_they_were_written(kind: ExportKind) -> None:
    assert kind_formats(kind) == _KIND_FORMATS[kind]


@pytest.mark.parametrize("name, suffix", sorted(_FORMAT_SUFFIX.items()))
def test_the_suffix_of_a_format_is_derived_as_it_was_written(name: str, suffix: str) -> None:
    assert format_suffix(name) == suffix


@pytest.mark.parametrize("suffix, name", sorted(_SUFFIX_TO_FORMAT.items()))
def test_an_extension_names_the_format_it_named(suffix: str, name: str) -> None:
    assert suffix_format(suffix) == name


def test_the_known_extensions_are_the_ones_the_request_names() -> None:
    assert known_extensions() == tuple(sorted(_SUFFIX_TO_FORMAT))


def test_an_extension_two_view_files_share_names_neither() -> None:
    assert suffix_format(".json") is None


def test_the_one_instant_and_non_reprojecting_formats_are_derived() -> None:
    assert one_instant_formats() == frozenset({"geotiff", "shapefile", "geopackage", "vtu"})
    assert non_reprojecting_formats() == frozenset({"netcdf", "vtu", "csv"})


def test_the_views_are_the_formats_that_describe_the_whole_run() -> None:
    views = run_formats()
    assert "rocrate" in views
    for name in views:
        assert "run" in export_formats.get(name).writes


@pytest.mark.parametrize("name, filename", sorted(_RUN_FORMAT_FILES.items()))
def test_a_view_filename_comes_from_the_storage_contract(name: str, filename: str) -> None:
    assert view_filename(name) == filename == _RUN_FORMAT_FILES[name]


def test_an_unknown_format_is_refused_with_the_formats_served() -> None:
    with pytest.raises(ValueError) as raised:
        check_format_name("datapackage")
    message = str(raised.value)
    assert "export.format names 'datapackage'" in message
    for served in ("csv", "geotiff", "netcdf", "rocrate", "vtu"):
        assert served in message
    assert "hydromodpy.export.format" in message
    assert check_format_name("netcdf") == "netcdf"


def test_every_served_format_declares_the_port() -> None:
    from hydromodpy.results.exporters.port import EXPORT_WRITER_MEMBERS

    for name in export_formats.names():
        cls = export_formats.get(name)
        for member in EXPORT_WRITER_MEMBERS:
            assert getattr(cls, member, None) is not None, (name, member)
        assert cls.help


def test_the_value_docs_of_the_format_field_name_the_formats_this_build_ships() -> None:
    from hydromodpy.results.exporters.export_spec import ExportRequest

    schema = ExportRequest.model_json_schema()
    docs = schema["properties"]["format"]["value_docs"]
    assert set(docs) == set(export_formats.names(shipped_only=True))
    assert all(text for text in docs.values())


class _FailingEntryPoint:
    """The entry point of the annex, on an installation where it cannot load."""

    name = "stac"
    value = "hydromodpy_annex.export.stac:StacItemView"

    def load(self):
        raise ModuleNotFoundError("No module named 'hydromodpy_annex'")


def test_a_declared_format_that_cannot_be_imported_is_refused_with_its_reason(
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
