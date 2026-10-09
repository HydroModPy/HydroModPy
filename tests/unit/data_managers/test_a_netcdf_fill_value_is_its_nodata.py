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

from hydromodpy.data.ingest.custom_grids import load_custom_nc


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
