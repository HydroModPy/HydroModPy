from __future__ import annotations

from datetime import datetime

import pytest

from hydromodpy.core.exceptions import ConfigMissingError, DataContractViolation
from hydromodpy.data.contracts.spatial_field import FieldRecord
from hydromodpy.data.variables.dem.config import DemConfig, IgnGeoplateformeDemSource
from hydromodpy.data.variables.hydrometry.config import HydrometryConfig
from hydromodpy.workflow.site_selection import data_loading
from hydromodpy.workflow.site_selection.catchments_csv import load_delineated_catchments_csv
from tests._helpers.site_selection_cases import (
    dem_loader_spy,
    make_point_record,
    selection_section,
    write_selection_toml,
)

pytestmark = pytest.mark.fast

HUBEAU = [{"source": "hubeau", "product": "QmnJ"}]


@pytest.mark.parametrize(
    ("dates", "explicit", "expected"),
    [
        (("2020-01-01", "2020-01-10"), None, (datetime(2020, 1, 1), datetime(2020, 1, 10))),
        (("2020-01-01", "2020-01-10"), (datetime(2021, 1, 1), datetime(2021, 1, 2)), None),
        ((None, None), None, None),
    ],
)
def test_the_hydrometry_period_comes_from_the_call_then_the_config(dates, explicit, expected):
    calls: dict = {}
    cfg = HydrometryConfig(date_start=dates[0], date_end=dates[1], sources=HUBEAU)

    loader = lambda **kwargs: calls.update(kwargs) or [make_point_record()]  # noqa: E731

    records = data_loading.load_hydrometry_records(cfg, project_period=explicit, loader=loader)

    assert len(records) == 1 and calls["config"] is cfg
    assert calls["project_period"] == (explicit or expected)


def test_a_geoplateforme_dem_is_asked_for_the_project_extent(tmp_path):
    dem = tmp_path / "dem.tif"
    dem.touch()
    calls: list = []
    extent = (100_000.0, 6_700_000.0, 120_000.0, 6_720_000.0)
    cfg = DemConfig(sources=[IgnGeoplateformeDemSource(regions=["Bretagne"])])

    assert (
        data_loading.load_dem_path(cfg, project_extent=extent, loader=dem_loader_spy(dem, calls))
        == dem
    )
    assert calls[0]["config"].sources[0].extent == "study_area"
    assert calls[0]["project_extent"] == extent
    data_loading.load_dem_path(cfg, loader=dem_loader_spy(dem, calls))
    assert calls[1]["config"] is cfg


def _field(data) -> FieldRecord:
    return FieldRecord(variable="dem", source="custom", unit="m", data=data, bbox=None, crs="EPSG:2154")  # fmt: skip


@pytest.mark.parametrize(
    ("fields", "error", "match"),
    [
        ([], DataContractViolation, "did not return any field"),
        ([_field(None)], DataContractViolation, "in-memory field"),
        ([_field("absent.tif")], FileNotFoundError, "missing path"),
    ],
)
def test_a_dem_the_data_layer_cannot_hand_as_a_file_is_refused(tmp_path, fields, error, match):
    cfg = DemConfig.model_validate({"sources": [{"source": "custom", "path": str(tmp_path)}]})

    with pytest.raises(error, match=match):
        data_loading.load_dem_path(
            cfg, project_extent=(0.0, 0.0, 1.0, 1.0), loader=lambda **_: fields
        )


def test_the_catchments_csv_reads_outlets_and_resolves_watershed_paths(tmp_path):
    (tmp_path / "catchments.csv").write_text(
        "site_id,x_outlet,y_outlet,x,y,outlet_crs,area_km2,watershed_shp,outlet_shp\n"
        "site_001,350000,6810000,,,EPSG:2154,100,vectors/site_001.geojson,/abs/o.shp\n"
        "site_002,,,351000,6811000,,,,\n",
        encoding="utf-8",
    )

    first, second = load_delineated_catchments_csv(tmp_path / "catchments.csv")

    assert (first.site_id, first.outlet.x, first.area_km2) == ("site_001", 350000.0, 100.0)
    assert first.watershed_shp == str((tmp_path / "vectors/site_001.geojson").resolve())
    assert first.outlet_shp == "/abs/o.shp"
    assert (second.outlet.x, second.outlet.crs, second.area_km2) == (351000.0, "EPSG:2154", None)
    assert second.status == "delineated" and second.watershed_shp is None


@pytest.mark.parametrize(
    ("row", "match"),
    [(",1,2", "missing required field 'site_id'"), ("a,,2", "missing numeric 'x_outlet'")],
)
def test_a_catchments_row_without_an_id_or_a_place_is_refused(tmp_path, row, match):
    (tmp_path / "catchments.csv").write_text(f"site_id,x,y\n{row}\n", encoding="utf-8")

    with pytest.raises(DataContractViolation, match=match):
        load_delineated_catchments_csv(tmp_path / "catchments.csv")


def test_the_hydrometry_section_resolves_custom_paths_against_the_file(tmp_path):
    (tmp_path / "hydrometry_data").mkdir()
    sources = [{"source": "custom", "path": "hydrometry_data"}, {"source": "hubeau"}]
    config_path = write_selection_toml(
        tmp_path, selection_section(), hydrometry={"sources": sources}
    )

    cfg = data_loading.load_hydrometry_config_for_site_selection(config_path)

    assert cfg.sources[0].path == (tmp_path / "hydrometry_data").resolve()
    assert cfg.sources[1].path is None


@pytest.mark.parametrize(
    ("load", "section"),
    [(data_loading.load_hydrometry_config_for_site_selection, "[hydrometry]"), (data_loading.load_site_selection_config, "[site_selection]")],
)  # fmt: skip
def test_a_file_without_the_section_is_refused(tmp_path, load, section):
    (tmp_path / "empty.toml").write_text("", encoding="utf-8")

    with pytest.raises(ConfigMissingError, match=section.replace("[", "\\[")):
        load(tmp_path / "empty.toml")
