"""LakeLevelsManager.load(): emits PointRecords keyed by lake_id.

Guards that the lake-levels manager follows the station-based
BaseVariableManager pattern: a custom CSV chronicle becomes a
``PointRecord`` on ``LoadResult.points`` whose ``station_id`` is the
lake id, and registers it as custom in the catalog.
"""

from __future__ import annotations

import pandas as pd

from hydromodpy.data.contracts.timeseries import PointRecord
from hydromodpy.data.variables.lake_levels.config import LakeLevelsConfig
from hydromodpy.data.variables.lake_levels.manager import LakeLevelsManager


class _RecordingCatalog:
    def __init__(self) -> None:
        self.registrations: list[dict] = []

    def register(self, **kwargs) -> int:
        self.registrations.append(kwargs)
        return len(self.registrations)


def _write_lake_levels(data_dir, lake_id: str) -> None:
    pd.DataFrame(
        {
            "id": [lake_id],
            "x": [350000.0],
            "y": [6800000.0],
            "crs": ["EPSG:2154"],
            "unit": ["m"],
        }
    ).to_csv(data_dir / "lake_levels_custom_LOC.csv", index=False)

    pd.DataFrame(
        {
            "datetime": ["2020-01-01", "2020-01-02", "2020-01-03"],
            "value": [85.0, 85.5, 86.0],
        }
    ).to_csv(
        data_dir / f"lake_levels_custom_{lake_id}_20200101_20200103_D.csv",
        index=False,
    )


def test_load_emits_point_record_keyed_by_lake_id(tmp_path) -> None:
    data_dir = tmp_path / "lake_levels"
    data_dir.mkdir()
    _write_lake_levels(data_dir, "lac0")

    config = LakeLevelsConfig.from_csv_directory(data_dir)
    catalog = _RecordingCatalog()
    manager = LakeLevelsManager(config=config, catalog=catalog, data_dir=data_dir)

    result = manager.load()

    assert result.has_points is True
    assert not result.has_fields
    assert not result.has_tables
    assert len(result.points) == 1

    rec = result.points[0]
    assert isinstance(rec, PointRecord)
    assert rec.variable == "lake_level"
    assert rec.source == "custom"
    assert rec.station_id == "lac0"
    assert rec.unit == "m"

    assert rec.data["value"].tolist() == [85.0, 85.5, 86.0]

    assert len(catalog.registrations) == 1
    reg = catalog.registrations[0]
    assert reg["variable"] == "lake_levels"
    assert reg["source"] == "custom"
    assert reg["is_custom"] is True
    assert reg["station_id"] == "lac0"
