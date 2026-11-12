"""An export request that cannot do what it says is refused, not half-done.

The refusals the request decides alone: a missing or empty ``variables``,
``time`` with ``period``, a ``file`` on a request that writes several files, a
``file`` whose extension contradicts ``format``, a ``resolution`` without a
raster, a run format with anything but ``"all"``, and a ``crs`` on a format
that does not reproject. :func:`plan_outputs` finishes with the kind of each
name. Several dates on a one-instant format are not refused: they write one
file per date.
"""

from __future__ import annotations

from pathlib import PureWindowsPath

import pytest
from pydantic import ValidationError

from hydromodpy.results.exporters.export_spec import ExportKind, ExportRequest, plan_outputs
from hydromodpy.results.exporters.registry import run_formats

F, S, V, R, T = (
    ExportKind.field,
    ExportKind.series,
    ExportKind.vector,
    ExportKind.raster,
    ExportKind.table,
)
KINDS = {
    "head": F,
    "watertable_depth": F,
    "discharge": S,
    "discharge_obs": S,
    "watershed": V,
    "hydrographic_network_reference": V,
    "watershed_dem": R,
    "budget": T,
}


def _plan(request: ExportRequest, **kwargs) -> list[str]:
    return [str(item.path) for item in plan_outputs(request, KINDS, run_label="nancon", **kwargs)]


class TestTheRequestRefusesWhatItCanDecideAlone:
    def test_variables_missing(self) -> None:
        with pytest.raises(ValidationError, match="variables is missing"):
            ExportRequest.model_validate({"time": "last"})

    @pytest.mark.parametrize("value", ["", [], [""]])
    def test_variables_empty(self, value) -> None:
        with pytest.raises(ValidationError, match="variables is empty"):
            ExportRequest(variables=value)

    def test_all_mixed_with_names(self) -> None:
        with pytest.raises(ValidationError, match='mixes "all" with names'):
            ExportRequest(variables=["all", "head"])

    def test_time_and_period_together(self) -> None:
        with pytest.raises(ValidationError, match="time and period are both given"):
            ExportRequest(variables="head", time="last", period=["2000-01-01", "2000-12-31"])

    def test_file_on_several_names_of_a_one_instant_format(self) -> None:
        with pytest.raises(ValidationError, match="2 names write one file each"):
            ExportRequest(variables=["head", "watertable_depth"], time="last", file="h.tif")

    def test_file_on_several_dates_of_a_one_instant_format(self) -> None:
        with pytest.raises(ValidationError, match="2 dates write one file each"):
            ExportRequest(variables="head", time=["2001-01-15", "2001-08-15"], file="h.tif")

    def test_file_extension_contradicting_format(self) -> None:
        with pytest.raises(ValidationError, match="names a geotiff file"):
            ExportRequest(variables="discharge", format="csv", file="series.tif")

    def test_file_without_a_known_extension(self) -> None:
        with pytest.raises(ValidationError, match="no extension a format is known by"):
            ExportRequest(variables="head", file="fields")

    def test_resolution_on_a_format_that_is_no_raster(self) -> None:
        with pytest.raises(ValidationError, match="sizes the pixels of a GeoTIFF"):
            ExportRequest(variables="head", format="geopackage", time="last", resolution=10.0)

    def test_a_run_format_takes_all_only(self) -> None:
        for fmt in run_formats():
            with pytest.raises(ValidationError, match='Write variables = "all"'):
                ExportRequest(variables="head", format=fmt)

    def test_a_run_format_refuses_a_selector(self) -> None:
        with pytest.raises(ValidationError, match="time selects nothing"):
            ExportRequest(variables="all", format="rocrate", time="last")

    @pytest.mark.parametrize("fmt", ["netcdf", "vtu", "csv"])
    def test_crs_on_a_format_that_does_not_reproject(self, fmt: str) -> None:
        with pytest.raises(ValidationError, match="does not reproject"):
            ExportRequest(variables="head", format=fmt, crs="EPSG:4326")

    @pytest.mark.parametrize(
        ("time", "match"),
        [
            ("all", "leave time out"),
            ("middle", "is not a date"),
            ("now", "is not a date"),
            (True, "is a boolean"),
            ([], "names no instant"),
        ],
    )
    def test_a_time_that_is_no_instant(self, time, match: str) -> None:
        with pytest.raises(ValidationError, match=match):
            ExportRequest(variables="head", time=time)

    def test_a_period_that_ends_before_it_starts(self) -> None:
        with pytest.raises(ValidationError, match="ends before it starts"):
            ExportRequest(variables="discharge", period=["2002-12-31", "2001-01-01"])

    def test_a_period_of_keywords(self) -> None:
        with pytest.raises(ValidationError, match="is not two dates"):
            ExportRequest(variables="discharge", period=["first", "last"])


class TestTheRequestAcceptsWhatItSays:
    def test_all_is_everything(self) -> None:
        request = ExportRequest(variables=["all"])
        assert request.exports_all
        assert request.names == []

    def test_the_package_format_is_refused_with_what_replaces_it(self) -> None:
        with pytest.raises(ValidationError, match="hmp publish <run> --to DEST --container tar"):
            ExportRequest(variables="all", format="package")


class TestThePlanNamesEveryFile:
    def test_all_with_a_format_takes_what_the_format_holds(self) -> None:
        request = ExportRequest(variables="all", format="csv")
        assert _plan(request, names=list(KINDS)) == [
            "nancon_series.csv",
            "budget.csv",
        ]


class TestThePlanSpellsANameAsTheTomlDoes:
    """On Windows ``folder`` and ``file`` load as Windows paths; the plan keeps forward slashes."""

    @staticmethod
    def _on_windows(request: ExportRequest, **paths: str) -> ExportRequest:
        return request.model_copy(
            update={key: PureWindowsPath(value) for key, value in paths.items()}
        )


class TestEveryFileStaysUnderTheExportsOfTheRun:
    @pytest.mark.parametrize("key", ["folder", "file"])
    def test_a_path_that_climbs_out_is_refused(self, key: str) -> None:
        value = "../elsewhere" if key == "folder" else "../h.tif"
        with pytest.raises(ValidationError, match="climbs out of runs/<run>/exports/"):
            ExportRequest(variables="head", time="last", **{key: value})


class TestThePlanRefusesWhatTheKindsMakeImpossible:
    def test_crs_that_would_miss_a_named_series(self) -> None:
        with pytest.raises(ValueError, match="does not reproject"):
            _plan(ExportRequest(variables=["watershed", "discharge"], crs="EPSG:4326"))

    def test_resolution_without_a_raster(self) -> None:
        with pytest.raises(ValueError, match="writes none"):
            _plan(ExportRequest(variables="head", resolution=50.0))

    def test_a_file_that_would_be_several(self) -> None:
        with pytest.raises(ValueError, match="writes 2 files"):
            _plan(ExportRequest(variables=["discharge", "budget"], file="x.csv"))

    def test_a_file_that_would_be_one_per_step(self) -> None:
        with pytest.raises(ValueError, match="one file per date"):
            _plan(ExportRequest(variables="head", file="h.tif"))
