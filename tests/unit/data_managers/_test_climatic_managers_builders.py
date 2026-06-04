"""Shared builders for the climatic data manager test split.

Record factories used by more than one of the split test files
(load result, base manager, recharge bridge).
"""

from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd
import xarray as xr

from hydromodpy.data.contracts.spatial_field import FieldRecord
from hydromodpy.data.contracts.timeseries import PointRecord


def _make_point_record(station_id: str = "ST01", n: int = 5) -> PointRecord:
    df = pd.DataFrame(
        {
            "datetime": pd.date_range("2020-01-01", periods=n, freq="D"),
            "value": range(n),
        }
    )
    return PointRecord(
        station_id=station_id,
        variable="recharge",
        source="custom",
        unit="mm/d",
        frequency="D",
        data=df,
        date_start=datetime(2020, 1, 1),
        date_end=datetime(2020, 1, n),
    )


def _make_field_record(variable: str = "recharge") -> FieldRecord:
    ds = xr.Dataset({"data": (["x", "y"], np.zeros((3, 3)))})
    return FieldRecord(
        variable=variable,
        source="sim2",
        unit="mm/d",
        source_unit="m/day",
        data=ds,
        bbox=(100.0, 200.0, 300.0, 400.0),
        crs="EPSG:2154",
        date_start=datetime(2020, 1, 1),
        date_end=datetime(2020, 12, 31),
    )
