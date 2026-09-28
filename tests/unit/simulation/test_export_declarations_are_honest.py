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

from pathlib import Path, PurePath

import pytest
from pydantic import ValidationError

from hydromodpy.core.config_kit.export_spec import (
    STEP_DATE_TOKEN,
    ExportFormat,
    ExportKind,
    ExportRequest,
    format_from_path,
    plan_outputs,
)

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

    @pytest.mark.parametrize("fmt", ["package", "stac", "rocrate", "prov"])
    def test_a_run_format_takes_all_only(self, fmt: str) -> None:
        with pytest.raises(ValidationError, match='Write variables = "all"'):
            ExportRequest(variables="head", format=fmt)

    def test_a_run_format_refuses_a_selector(self) -> None:
        with pytest.raises(ValidationError, match="time selects nothing"):
            ExportRequest(variables="all", format="package", time="last")

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

    def test_an_unknown_key(self) -> None:
        with pytest.raises(ValidationError):
            ExportRequest.model_validate({"variables": "head", "var": "head"})


class TestTheRequestAcceptsWhatItSays:
    def test_several_dates_on_a_one_instant_format_write_one_file_each(self) -> None:
        request = ExportRequest(
            variables="head", time=["2001-01-15", "2001-08-15"], format="geotiff"
        )
        assert _plan(request) == [
            "nancon/head_2001-01-15.tif",
            "nancon/head_2001-08-15.tif",
        ]

    def test_the_extension_gives_the_format(self) -> None:
        assert ExportRequest(variables="head", file="fields.nc").output_format is (
            ExportFormat.netcdf
        )
        assert format_from_path("run.hmp") is ExportFormat.package
        assert format_from_path(Path("layer.GPKG")) is ExportFormat.geopackage

    def test_an_integer_stays_a_step_index(self) -> None:
        assert ExportRequest(variables="head", time=33).times == [33]

    def test_keywords_and_dates(self) -> None:
        request = ExportRequest(variables="head", time=["First", "2002-10-15"])
        assert request.times == ["first", "2002-10-15"]

    def test_all_is_everything(self) -> None:
        request = ExportRequest(variables=["all"])
        assert request.exports_all
        assert request.names == []

    def test_a_package_of_the_run(self) -> None:
        request = ExportRequest(variables="all", format="package")
        assert _plan(request) == ["nancon/nancon.hmp"]


class TestThePlanNamesEveryFile:
    def test_a_field_at_one_date_is_a_geotiff_per_variable(self) -> None:
        request = ExportRequest(variables=["head", "watertable_depth"], time="2001-08-15")
        assert _plan(request) == [
            "nancon/head_2001-08-15.tif",
            "nancon/watertable_depth_2001-08-15.tif",
        ]

    def test_a_field_over_the_record_is_one_netcdf(self) -> None:
        request = ExportRequest(variables=["head", "watertable_depth"])
        assert _plan(request) == ["nancon/nancon_fields.nc"]

    def test_a_period_names_its_window(self) -> None:
        request = ExportRequest(
            variables=["discharge", "discharge_obs"], period=["2001-01-01", "2002-12-31"]
        )
        assert _plan(request) == ["nancon/nancon_series_2001-01-01_2002-12-31.csv"]

    def test_layers_and_tables_take_their_natural_format(self) -> None:
        request = ExportRequest(
            variables=["watershed", "hydrographic_network_reference", "watershed_dem", "budget"]
        )
        assert _plan(request) == [
            "nancon/watershed.gpkg",
            "nancon/hydrographic_network_reference.gpkg",
            "nancon/watershed_dem.tif",
            "nancon/budget.csv",
        ]

    def test_a_step_index_and_a_keyword_in_a_name(self) -> None:
        assert _plan(ExportRequest(variables="head", time=33)) == ["nancon/head_step33.tif"]
        assert _plan(ExportRequest(variables="head", time="last")) == ["nancon/head_last.tif"]

    def test_a_one_instant_format_over_the_record_writes_one_file_per_step(self) -> None:
        (planned,) = plan_outputs(
            ExportRequest(variables="head", format="vtu"), KINDS, run_label="nancon"
        )
        assert planned.per_step
        assert planned.path == PurePath("nancon", f"head_{STEP_DATE_TOKEN}.vtu")

    def test_a_file_replaces_the_automatic_name_inside_the_folder(self) -> None:
        request = ExportRequest(
            variables="watertable_depth", time="last", file="wgs84.tif", crs="EPSG:4326"
        )
        assert _plan(request) == ["nancon/wgs84.tif"]
        request = ExportRequest(variables="head", folder="deliver", file="h.nc")
        assert _plan(request) == ["deliver/h.nc"]

    def test_all_with_a_format_takes_what_the_format_holds(self) -> None:
        request = ExportRequest(variables="all", format="csv")
        assert _plan(request, names=list(KINDS)) == [
            "nancon/nancon_series.csv",
            "nancon/budget.csv",
        ]

    def test_all_plans_nothing_before_the_run(self) -> None:
        assert _plan(ExportRequest(variables="all")) == []


class TestThePlanRefusesWhatTheKindsMakeImpossible:
    def test_a_kind_the_format_cannot_hold(self) -> None:
        with pytest.raises(ValueError, match="'watershed' is a vector"):
            _plan(ExportRequest(variables="watershed", format="netcdf"))

    def test_a_field_in_csv(self) -> None:
        with pytest.raises(ValueError, match="'head' is a field"):
            _plan(ExportRequest(variables="head", format="csv"))

    def test_crs_on_a_natural_format_that_does_not_reproject(self) -> None:
        with pytest.raises(ValueError, match="does not reproject"):
            _plan(ExportRequest(variables="discharge", crs="EPSG:4326"))

    def test_crs_that_would_miss_a_named_series(self) -> None:
        with pytest.raises(ValueError, match="does not reproject"):
            _plan(ExportRequest(variables=["watershed", "discharge"], crs="EPSG:4326"))

    def test_crs_on_all_reprojects_what_can_be(self) -> None:
        request = ExportRequest(variables="all", crs="EPSG:4326")
        assert "nancon/watershed.gpkg" in _plan(request, names=list(KINDS))

    def test_resolution_without_a_raster(self) -> None:
        with pytest.raises(ValueError, match="writes none"):
            _plan(ExportRequest(variables="head", resolution=50.0))

    def test_a_file_that_would_be_several(self) -> None:
        with pytest.raises(ValueError, match="writes 2 files"):
            _plan(ExportRequest(variables=["discharge", "budget"], file="x.csv"))

    def test_a_file_that_would_be_one_per_step(self) -> None:
        with pytest.raises(ValueError, match="one file per date"):
            _plan(ExportRequest(variables="head", file="h.tif"))
