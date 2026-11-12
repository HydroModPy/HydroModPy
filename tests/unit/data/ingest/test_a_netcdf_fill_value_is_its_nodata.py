"""A NetCDF grid that declares ``_FillValue`` declares its nodata value.

xarray moves ``_FillValue`` from the attributes of a variable to its encoding
when it opens the file, so a grid with a ``_FillValue`` and no ``nodata``
attribute used to be refused as declaring no nodata value.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import numpy as np
import pytest
import xarray as xr

from hydromodpy.data.ingest.custom_grids import load_custom_nc, load_custom_tif


def _grid(path: Path, *, fill_value: float | None) -> Path:
    data = np.full((3, 2, 2), 1.5, dtype="float32")
    data[0, 0, 0] = -999.0
    ds = xr.Dataset(
        {"recharge": (("time", "y", "x"), data, {"units": "mm/day"})},
        coords={
            "time": np.array(["2020-01-01", "2020-01-02", "2020-01-03"], dtype="datetime64[ns]"),
            "y": [6790000.0, 6789975.0],
            "x": [350000.0, 350025.0],
        },
        attrs={"crs": "EPSG:2154"},
    )
    # None writes no fill value at all: the NetCDF writer adds NaN by default.
    ds.to_netcdf(path, encoding={"recharge": {"_FillValue": fill_value}})
    return path


@pytest.mark.fast
def test_the_fill_value_is_read_as_nodata(tmp_path: Path) -> None:
    path = _grid(tmp_path / "recharge.nc", fill_value=-999.0)

    (record,) = load_custom_nc(
        path,
        variable="recharge",
        unit="mm/day",
        project_period=(datetime(2020, 1, 1), datetime(2020, 1, 3)),
    )

    assert float(record.data["recharge"].attrs["nodata"]) == -999.0
    assert np.isnan(float(record.data["recharge"].isel(time=0, y=0, x=0)))


@pytest.mark.fast
def test_a_grid_without_any_nodata_is_still_refused(tmp_path: Path) -> None:
    path = _grid(tmp_path / "recharge.nc", fill_value=None)

    with pytest.raises(ValueError, match="must declare a nodata value"):
        load_custom_nc(path, variable="recharge", unit="mm/day")


def _tif_with_nodata(path: Path) -> Path:
    import rasterio
    from rasterio.transform import from_origin

    data = np.full((2, 2), 1.5, dtype="float32")
    data[0, 0] = -9999.0
    profile = {
        "driver": "GTiff",
        "height": 2,
        "width": 2,
        "count": 1,
        "dtype": "float32",
        "crs": "EPSG:2154",
        "transform": from_origin(350000.0, 6790000.0, 25.0, 25.0),
        "nodata": -9999.0,
    }
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(data, 1)
    return path


def _nc_with_nodata_attribute(path: Path) -> Path:
    data = np.full((3, 2, 2), 1.5, dtype="float32")
    data[:, 0, 0] = -9999.0
    attrs = {"units": "mm/day", "nodata": -9999.0}
    times = np.array(["2020-01-01", "2020-01-02", "2020-01-03"], dtype="datetime64[ns]")
    coords = {"time": times, "y": [6790000.0, 6789975.0], "x": [350000.0, 350025.0]}
    xr.Dataset(
        {"recharge": (("time", "y", "x"), data, attrs)}, coords=coords, attrs={"crs": "EPSG:2154"}
    ).to_netcdf(path)
    return path


@pytest.mark.fast
@pytest.mark.parametrize(
    ("name", "write", "load"),
    [
        ("recharge.tif", _tif_with_nodata, lambda p: load_custom_tif(p, variable="recharge", unit="m/day", source_unit="mm/day")),
        ("recharge.nc", _nc_with_nodata_attribute, lambda p: load_custom_nc(p, variable="recharge", unit="m/day")),
    ],
    ids=["geotiff", "netcdf-nodata-attribute"],
)  # fmt: skip
def test_a_nodata_pixel_stays_masked_through_a_unit_conversion(
    tmp_path: Path, name, write, load
) -> None:
    (record,) = load(write(tmp_path / name))

    values = record.data["recharge"].values.reshape(-1, 4)[0]
    assert np.isnan(values[0]) or values[0] == float(record.data["recharge"].attrs["nodata"])
    assert values[1] == pytest.approx(1.5e-3)


@pytest.mark.fast
def test_a_window_outside_the_file_names_the_period(tmp_path: Path) -> None:
    path = _grid(tmp_path / "recharge.nc", fill_value=-999.0)

    with pytest.raises(ValueError, match="holds no date in the period"):
        load_custom_nc(
            path,
            variable="recharge",
            unit="mm/day",
            project_period=(datetime(2030, 1, 1), datetime(2030, 1, 2)),
        )
