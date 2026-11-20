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


def test_a_numpy_dem_is_accepted() -> None:
    dem = {"data": np.full((10, 10), 100.0), "resolution": (25.0, 25.0), "crs": "EPSG:2154"}
    out = validate_dem(dem)
    assert out["crs"] == "EPSG:2154"
    assert out["data"].shape == (10, 10)


GOOD_DEM = {"data": np.ones((10, 10)), "resolution": 25.0, "crs": "EPSG:2154"}
BAD_DEMS = [
    pytest.param(GOOD_DEM | {"crs": None}, "no CRS declared", id="no crs"),
    pytest.param(GOOD_DEM | {"resolution": 0.5}, "resolution", id="resolution out of range"),
    pytest.param(
        GOOD_DEM | {"data": np.full((3, 3), -10000.0)},
        "elevation range",
        id="elevation out of range",
    ),
]


@pytest.mark.parametrize(("dem", "says"), BAD_DEMS)
def test_a_dem_out_of_contract_is_refused(dem, says) -> None:
    with pytest.raises(DataContractViolation) as refused:
        validate_dem(dem)
    assert any(says in str(f) for f in refused.value.context["failures"])


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


def test_an_undeclared_sentinel_is_read_as_an_elevation_and_refused(tmp_path) -> None:
    path = write_geotiff(tmp_path / "dem.tif", np.full((3, 3), -9999.0), nodata=None)

    with rasterio.open(path) as src, pytest.raises(DataContractViolation) as refused:
        check_dem_values(src, _header(nodata=None))
    assert any("declared as nodata" in str(f) for f in refused.value.context["failures"])
