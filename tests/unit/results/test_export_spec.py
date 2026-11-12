"""An export request says what to write, and a request that cannot do it is refused.

``[[export]]`` on the root config is an array of requests, each refusal naming its
block. A request decides alone what it can (names, time, period, file, format,
crs, resolution). ``plan_outputs`` then names every file from the kind of each
variable. Several dates on a one-instant format are not refused: they write one
file per date.
"""

from __future__ import annotations

import re
import textwrap
from pathlib import Path

import pytest
from pydantic import ValidationError

from hydromodpy.config.hydromodpy_config import HydroModPyConfig
from hydromodpy.core.exceptions import ConfigValidationError
from hydromodpy.results.exporters.export_spec import (
    ExportKind,
    ExportRequest,
    load_export_requests,
    plan_outputs,
)
from hydromodpy.results.exporters.registry import run_formats

HEAD_OF_TOML = """\
[workspace]

[workflow]
mode = "simulation"

[geographic]
source_mode = "synthetic"

"""

KINDS = {
    "head": ExportKind.field,
    "watertable_depth": ExportKind.field,
    "discharge": ExportKind.series,
    "discharge_obs": ExportKind.series,
    "watershed": ExportKind.vector,
    "hydrographic_network_reference": ExportKind.vector,
    "watershed_dem": ExportKind.raster,
    "budget": ExportKind.table,
}


def load_config(tmp_path: Path, body: str) -> HydroModPyConfig:
    path = tmp_path / "project.toml"
    path.write_text(HEAD_OF_TOML + textwrap.dedent(body), encoding="utf-8")
    return HydroModPyConfig.from_toml(path)


def plan(request: ExportRequest, **kwargs) -> list[str]:
    return [str(item.path) for item in plan_outputs(request, KINDS, run_label="nancon", **kwargs)]


def test_blocks_load_in_file_order(tmp_path):
    cfg = load_config(
        tmp_path,
        """\
        [[export]]
        variables = ["head", "watertable_depth"]
        time = 2002-10-15

        [[export]]
        variables = "all"
        format = "rocrate"
        """,
    )

    assert [request.variables for request in cfg.export] == [["head", "watertable_depth"], "all"]
    # A bare TOML date reads as the date it names.
    assert cfg.export[0].time == "2002-10-15"


def test_table_instead_of_array_is_refused(tmp_path):
    with pytest.raises(ConfigValidationError, match=r"write \[\[export\]\]"):
        load_config(tmp_path, '[export]\nvariables = "head"\nformat = "netcdf"\n')


def test_empty_document_is_no_request():
    assert load_export_requests(None) == []
    assert load_export_requests([]) == []


def test_export_is_a_list_on_the_root_config():
    from hydromodpy.solver.base.results_config import ResultsConfig

    assert HydroModPyConfig.model_fields["export"].default_factory is list
    assert "export" not in ResultsConfig.model_fields


def test_view_with_a_folder_delivers_its_files(tmp_path):
    cfg = load_config(
        tmp_path,
        """\
        [[export]]
        variables = "all"
        format = "rocrate"
        folder = "views"
        deliver_to = "/srv/depot/"
        """,
    )

    assert cfg.export[0].deliver_to == ["/srv/depot/"]


DELIVERY_REFUSED = [
    pytest.param('deliver_to = "livrables/nancon"', "is a relative path", id="relative path"),
    pytest.param(
        'deliver_to = "https://zenodo.org/deposit/1"',
        "uses https://, which HydroModPy does not deliver to",
        id="other scheme",
    ),
    pytest.param(
        'deliver_to = "ftp://bb:secret@data.example.org/depot/"',
        "carries a user or a password",
        id="identity in the address",
    ),
    pytest.param(
        'deliver_to = "ftp://data.example.org/depot/?case=a"',
        "carries a query or a fragment",
        id="query",
    ),
    pytest.param('deliver_to = "ftp:///depot/"', "names no host", id="no host"),
    pytest.param("deliver_to = []", "deliver_to is empty", id="empty list"),
    pytest.param(
        'deliver_to = ["/srv/depot/", "/srv/depot/"]',
        "deliver_to names '/srv/depot/' twice.",
        id="same destination twice",
    ),
    pytest.param(
        'deliver_to = "/srv/depot/head.tif"', "names one remote file", id="file without a file"
    ),
    pytest.param(
        'format = "rocrate"\nvariables = "all"\ndeliver_to = "/srv/depot/"',
        "a view is delivered from exports",
        id="view without folder or file",
    ),
]


@pytest.mark.parametrize(("lines", "phrase"), DELIVERY_REFUSED)
def test_delivery_refusals(tmp_path, lines, phrase):
    body = lines if "variables" in lines else 'variables = "head"\n' + lines
    with pytest.raises(ConfigValidationError, match=re.escape(phrase)):
        load_config(tmp_path, "[[export]]\n" + body + "\n")


REQUEST_REFUSED = [
    pytest.param({"time": "last"}, "variables is missing", id="variables missing"),
    pytest.param({"variables": ""}, "variables is empty", id="empty string"),
    pytest.param({"variables": []}, "variables is empty", id="empty list"),
    pytest.param({"variables": [""]}, "variables is empty", id="list of an empty name"),
    pytest.param({"variables": ["all", "head"]}, 'mixes "all" with names', id="all with names"),
    pytest.param(
        {"variables": "head", "time": "last", "period": ["2000-01-01", "2000-12-31"]},
        "time and period are both given",
        id="time and period",
    ),
    pytest.param(
        {"variables": ["head", "watertable_depth"], "time": "last", "file": "h.tif"},
        "2 names write one file each",
        id="file on two names",
    ),
    pytest.param(
        {"variables": "head", "time": ["2001-01-15", "2001-08-15"], "file": "h.tif"},
        "2 dates write one file each",
        id="file on two dates",
    ),
    pytest.param(
        {"variables": "discharge", "format": "csv", "file": "series.tif"},
        "names a geotiff file",
        id="extension against format",
    ),
    pytest.param(
        {"variables": "head", "file": "fields"},
        "no extension a format is known by",
        id="file without extension",
    ),
    pytest.param(
        {"variables": "head", "format": "geopackage", "time": "last", "resolution": 10.0},
        "sizes the pixels of a GeoTIFF",
        id="resolution without a raster",
    ),
    pytest.param(
        {"variables": "all", "format": "rocrate", "time": "last"},
        "time selects nothing",
        id="selector on a run format",
    ),
    pytest.param(
        {"variables": "head", "format": "netcdf", "crs": "EPSG:4326"},
        "does not reproject",
        id="crs on netcdf",
    ),
    pytest.param(
        {"variables": "head", "format": "vtu", "crs": "EPSG:4326"},
        "does not reproject",
        id="crs on vtu",
    ),
    pytest.param(
        {"variables": "head", "format": "csv", "crs": "EPSG:4326"},
        "does not reproject",
        id="crs on csv",
    ),
    pytest.param({"variables": "head", "time": "all"}, "leave time out", id="time all"),
    pytest.param({"variables": "head", "time": "middle"}, "is not a date", id="time middle"),
    pytest.param({"variables": "head", "time": "now"}, "is not a date", id="time now"),
    pytest.param({"variables": "head", "time": True}, "is a boolean", id="time boolean"),
    pytest.param({"variables": "head", "time": []}, "names no instant", id="empty time list"),
    pytest.param(
        {"variables": "discharge", "period": ["2002-12-31", "2001-01-01"]},
        "ends before it starts",
        id="period backwards",
    ),
    pytest.param(
        {"variables": "discharge", "period": ["first", "last"]},
        "is not two dates",
        id="period of keywords",
    ),
    pytest.param(
        {"variables": "all", "format": "package"},
        "hmp publish <run> --to DEST --container tar",
        id="package format",
    ),
    pytest.param(
        {"variables": "head", "time": "last", "folder": "../elsewhere"},
        "climbs out of runs/<run>/exports/",
        id="folder climbs out",
    ),
    pytest.param(
        {"variables": "head", "time": "last", "file": "../h.tif"},
        "climbs out of runs/<run>/exports/",
        id="file climbs out",
    ),
]


@pytest.mark.parametrize(("fields", "phrase"), REQUEST_REFUSED)
def test_request_refusals(fields, phrase):
    with pytest.raises(ValidationError, match=phrase):
        ExportRequest(**fields)


def test_run_format_takes_all_only():
    for fmt in run_formats():
        with pytest.raises(ValidationError, match='Write variables = "all"'):
            ExportRequest(variables="head", format=fmt)


def test_all_is_everything():
    request = ExportRequest(variables=["all"])

    assert request.exports_all
    assert request.names == []


def test_all_with_a_format_takes_what_it_holds():
    request = ExportRequest(variables="all", format="csv")

    assert plan(request, names=list(KINDS)) == ["nancon_series.csv", "budget.csv"]


PLAN_REFUSED = [
    pytest.param(
        {"variables": ["watershed", "discharge"], "crs": "EPSG:4326"},
        "does not reproject",
        id="crs misses a series",
    ),
    pytest.param(
        {"variables": "head", "resolution": 50.0}, "writes none", id="resolution without a raster"
    ),
    pytest.param(
        {"variables": ["discharge", "budget"], "file": "x.csv"},
        "writes 2 files",
        id="file for several",
    ),
    pytest.param(
        {"variables": "head", "file": "h.tif"}, "one file per date", id="file for one per step"
    ),
]


@pytest.mark.parametrize(("fields", "phrase"), PLAN_REFUSED)
def test_plan_refusals(fields, phrase):
    with pytest.raises(ValueError, match=phrase):
        plan(ExportRequest(**fields))
