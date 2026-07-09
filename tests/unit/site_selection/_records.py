from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd

from hydromodpy.data.contracts.location import StationLocation
from hydromodpy.data.contracts.timeseries import PointRecord


def make_point_record(
    station_id: str = "J123456701",
    *,
    x: float = 0.0,
    y: float = 0.0,
    crs: str = "EPSG:2154",
    metadata: dict[str, object] | None = None,
    n_values: int = 1,
    source: str = "hubeau",
    with_location: bool = True,
) -> PointRecord:
    start = datetime(2020, 1, 1)
    end = start + timedelta(days=max(n_values, 1) - 1)
    station_metadata = {"station_name": f"Station {station_id}"}
    if metadata:
        station_metadata.update(metadata)
    location = (
        StationLocation(
            id=station_id,
            x=x,
            y=y,
            crs=crs,
            metadata=station_metadata,
        )
        if with_location
        else None
    )
    return PointRecord(
        station_id=station_id,
        variable="discharge",
        source=source,
        unit="m3/s",
        frequency="D",
        data=pd.DataFrame(
            {
                "datetime": [start + timedelta(days=day) for day in range(n_values)],
                "value": [float(day + 1) for day in range(n_values)],
            }
        ),
        date_start=start,
        date_end=end,
        location=location,
    )
