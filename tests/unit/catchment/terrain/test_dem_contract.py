"""The header, value and outlet contract a DEM must hold before routing."""

from __future__ import annotations

import numpy as np
import pytest
import rasterio
from rasterio.crs import CRS

from hydromodpy.catchment.terrain.dem_contract import (
    DEMContract,
    DemHeader,
    check_dem_header,
    check_dem_outlet,
    check_dem_values,
    read_dem_header,
    validate_dem,
)
from hydromodpy.core.exceptions import DataContractViolation
from tests._helpers.geotiffs import write_geotiff


def _header(**overrides) -> DemHeader:
    facts = {
        "crs": "EPSG:2154",
        "projected": True,
        "linear_unit": "metre",
        "metric": True,
        "rotated": False,
        "dx_m": 25.0,
        "dy_m": 25.0,
        "nodata": -9999.0,
    }
    facts.update(overrides)
    return DemHeader(**facts)


# -- validate_dem, moved from the old data.schemas.dem ------------------------


def test_dem_valid_numpy_dict():
    dem = {
        "data": np.ones((10, 10)) * 100.0,
        "resolution": (25.0, 25.0),
        "crs": "EPSG:2154",
    }
    out = validate_dem(dem)
    assert out["crs"] == "EPSG:2154"
    assert out["data"].shape == (10, 10)


def test_dem_missing_crs_fails():
    dem = {
        "data": np.ones((10, 10)),
        "resolution": 25.0,
        "crs": None,
    }
    with pytest.raises(DataContractViolation):
        validate_dem(dem)


def test_dem_resolution_out_of_range_fails():
    dem = {
        "data": np.ones((10, 10)),
        "resolution": 0.5,
        "crs": "EPSG:2154",
    }
    with pytest.raises(DataContractViolation):
        validate_dem(dem)


def test_dem_elevation_out_of_range_fails():
    dem = {
        "data": np.full((3, 3), -10000.0),
        "resolution": 25.0,
        "crs": "EPSG:2154",
    }
    with pytest.raises(DataContractViolation) as refused:
        validate_dem(dem)
    assert any("elevation range" in str(f) for f in refused.value.context["failures"])


# -- read_dem_header -----------------------------------------------------------


def test_the_header_reads_the_facts_without_reading_values(tmp_path) -> None:
    path = write_geotiff(tmp_path / "dem.tif", np.ones((4, 4)), cell=25.0, nodata=-9999.0)

    with rasterio.open(path) as src:
        header = read_dem_header(src)

    assert header.crs == "EPSG:2154"
    assert header.projected is True
    assert header.linear_unit == "metre"
    assert header.metric is True
    assert header.rotated is False
    assert header.dx_m == 25.0
    assert header.dy_m == 25.0
    assert header.nodata == -9999.0


# -- check_dem_header ----------------------------------------------------------


def test_a_projected_metre_square_header_passes() -> None:
    check_dem_header(_header(), routing_res_m=25.0)


@pytest.mark.parametrize(
    ("header", "says"),
    [
        (_header(crs=None, projected=False, linear_unit=None, metric=False), "declares no CRS"),
        (
            _header(crs="EPSG:4326", projected=False, linear_unit="degree", metric=False),
            "not a projected CRS in metres",
        ),
        (
            _header(crs="EPSG:2249", linear_unit="US survey foot", metric=False),
            "not a projected CRS in metres",
        ),
        (_header(rotated=True), "rotated"),
        (_header(dx_m=25.0, dy_m=30.0), "not square"),
    ],
)
def test_a_broken_header_is_refused_naming_the_fact(header: DemHeader, says: str) -> None:
    with pytest.raises(DataContractViolation) as refused:
        check_dem_header(header, routing_res_m=25.0)

    failures = refused.value.context["failures"]
    assert any(says in str(failure) for failure in failures)


def test_a_routed_resolution_outside_the_contract_is_refused() -> None:
    with pytest.raises(DataContractViolation) as refused:
        check_dem_header(_header(), routing_res_m=0.5)

    assert any(
        "routed resolution 0.5 m is outside" in str(f) for f in refused.value.context["failures"]
    )


def test_a_degree_resolution_is_not_read_as_metres() -> None:
    header = _header(crs="EPSG:4326", projected=False, linear_unit="degree", metric=False)

    with pytest.raises(DataContractViolation) as refused:
        check_dem_header(header, routing_res_m=0.0003)

    assert len(refused.value.context["failures"]) == 1


def test_a_metric_unit_is_known_by_its_factor_not_its_name(tmp_path) -> None:
    wkt = CRS.from_epsg(2154).to_wkt().replace('"metre"', '"metres"')
    path = write_geotiff(tmp_path / "dem.tif", np.ones((4, 4)), cell=25.0, nodata=-9999.0)
    with rasterio.open(path, "r+") as dst:
        dst.crs = CRS.from_wkt(wkt)

    with rasterio.open(path) as src:
        header = read_dem_header(src)

    assert header.metric is True
    check_dem_header(header, routing_res_m=25.0)


def test_the_contract_bounds_can_be_tightened() -> None:
    contract = DEMContract(min_resolution_m=20.0, max_resolution_m=100.0)
    with pytest.raises(DataContractViolation):
        check_dem_header(_header(), routing_res_m=10.0, contract=contract)


# -- check_dem_outlet ----------------------------------------------------------


def test_an_outlet_inside_the_raster_on_a_value_passes(tmp_path) -> None:
    path = write_geotiff(tmp_path / "dem.tif", np.ones((10, 10)), cell=25.0, nodata=-9999.0)

    with rasterio.open(path) as src:
        check_dem_outlet(src, _header(), x=100.0, y=100.0)


def test_an_outlet_outside_the_raster_is_refused(tmp_path) -> None:
    path = write_geotiff(tmp_path / "dem.tif", np.ones((10, 10)), cell=25.0)

    with rasterio.open(path) as src, pytest.raises(DataContractViolation) as refused:
        check_dem_outlet(src, _header(), x=10_000.0, y=10_000.0)
    assert any("outside the DEM raster" in str(f) for f in refused.value.context["failures"])


def test_an_outlet_on_a_nodata_cell_is_refused(tmp_path) -> None:
    data = np.full((10, 10), 10.0)
    data[5, 5] = -9999.0
    path = write_geotiff(tmp_path / "dem.tif", data, cell=25.0, nodata=-9999.0)

    with rasterio.open(path) as src, pytest.raises(DataContractViolation) as refused:
        check_dem_outlet(src, _header(), x=130.0, y=120.0)
    assert any("nodata cell" in str(f) for f in refused.value.context["failures"])


# -- check_dem_values ----------------------------------------------------------


def test_valid_elevations_pass(tmp_path) -> None:
    path = write_geotiff(tmp_path / "dem.tif", np.full((3, 3), 200.0), nodata=-9999.0)

    with rasterio.open(path) as src:
        check_dem_values(src, _header())


def test_an_undeclared_sentinel_is_read_as_an_elevation_and_refused(tmp_path) -> None:
    path = write_geotiff(tmp_path / "dem.tif", np.full((3, 3), -9999.0), nodata=None)

    with rasterio.open(path) as src, pytest.raises(DataContractViolation) as refused:
        check_dem_values(src, _header(nodata=None))
    assert any("declared as nodata" in str(f) for f in refused.value.context["failures"])
