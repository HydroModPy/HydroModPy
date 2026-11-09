"""Golden bytes of the sidecars the data cache writes.

Pins what ``CacheIndex.record`` and ``record_empty`` put on disk for a station
chronicle, a grid and a station that answered nothing: the keys, their order,
the indentation and the omitted fields. A change of the stored form must update
these bytes on purpose.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from hydromodpy.data.provenance.sidecars import (
    DETERMINISTIC_FETCHED_AT_ENV,
    CacheIndex,
    empty_path_for,
    sidecar_path_for,
)

pytestmark = pytest.mark.regression

_PAYLOAD_SHA256 = "239f59ed55e737c77147cf55ad0c1b030b6d7ee748a7426952f9b852d5a935e5"

GOLDEN_STATION = f"""{{
  "bbox": [
    -1.5,
    48.0,
    -1.5,
    48.0
  ],
  "bytes": 7,
  "crs": "EPSG:4326",
  "date_end": "2020-12-31T00:00:00",
  "date_start": "2020-01-01T00:00:00",
  "fetched_at": null,
  "frequency": "D",
  "license": "etalab-2.0",
  "notes": null,
  "product": "QmnJ",
  "sha256": "{_PAYLOAD_SHA256}",
  "source": "hubeau",
  "source_unit": "L/s",
  "station_id": "ST_A",
  "unit": "m3/s",
  "variable": "hydrometry"
}}
"""

GOLDEN_GRID = f"""{{
  "bbox": [
    0.0,
    43.0,
    5.0,
    48.0
  ],
  "bytes": 7,
  "crs": null,
  "date_end": "2024-12-31T00:00:00",
  "date_start": "2019-01-01T00:00:00",
  "fetched_at": null,
  "license": "etalab-2.0",
  "notes": null,
  "sha256": "{_PAYLOAD_SHA256}",
  "source": "sim2",
  "variable": "precipitation"
}}
"""

GOLDEN_EMPTY = """{
  "asked_window": [
    "2021-01-01T00:00:00",
    "2021-12-31T00:00:00"
  ],
  "bbox": null,
  "crs": null,
  "empty": true,
  "fetched_at": null,
  "license": "etalab-2.0",
  "notes": null,
  "source": "hubeau",
  "station_id": "ST_B",
  "variable": "hydrometry"
}
"""


def test_the_sidecars_match_golden(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(DETERMINISTIC_FETCHED_AT_ENV, "1")
    data_root = tmp_path / "data"
    station = data_root / "hydrometry" / "hydrometry_hubeau_ST_A_20200101_20201231_D.csv"
    grid = data_root / "precipitation" / "grid.nc"
    for path in (station, grid):
        path.parent.mkdir(parents=True)
        path.write_text("payload")
    index = CacheIndex(data_root)

    index.record(
        station,
        variable="hydrometry",
        source="hubeau",
        station_id="ST_A",
        product="QmnJ",
        bbox=(-1.5, 48.0, -1.5, 48.0),
        crs="EPSG:4326",
        date_start=datetime(2020, 1, 1),
        date_end=datetime(2020, 12, 31),
        frequency="D",
        unit="m3/s",
        source_unit="L/s",
    )
    index.record(
        grid,
        variable="precipitation",
        source="sim2",
        bbox=(0.0, 43.0, 5.0, 48.0),
        date_start=datetime(2019, 1, 1),
        date_end=datetime(2024, 12, 31),
    )
    empty = empty_path_for(data_root / "hydrometry", "hydrometry_hubeau_ST_B")
    index.record_empty(
        empty,
        variable="hydrometry",
        source="hubeau",
        station_id="ST_B",
        asked_window=(datetime(2021, 1, 1), datetime(2021, 12, 31)),
    )

    assert sidecar_path_for(station).read_text(encoding="utf-8") == GOLDEN_STATION
    assert sidecar_path_for(grid).read_text(encoding="utf-8") == GOLDEN_GRID
    assert sidecar_path_for(empty).read_text(encoding="utf-8") == GOLDEN_EMPTY
