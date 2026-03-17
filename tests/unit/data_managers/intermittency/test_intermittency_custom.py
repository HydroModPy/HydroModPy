"""Tests for intermittency custom loader and config validation."""

from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest

from hydromodpy.data_managers.variables.intermittency.config import (
    IntermittencyConfig,
    IntermittencySourceConfig,
)
from hydromodpy.data_managers.variables.intermittency.custom import load_custom
from hydromodpy.data_managers.variables.intermittency.manager import IntermittencyManager


@pytest.fixture
def sample_intermittency_dir(tmp_path):
    """Temporary directory with intermittency custom files (LOC + 2 chronicles)."""
    d = tmp_path / "intermittency"
    d.mkdir()

    pd.DataFrame({
        "id": ["ONDE_A", "ONDE_B"],
        "x": [-1.5, -1.6],
        "y": [48.1, 48.2],
        "crs": ["EPSG:4326", "EPSG:4326"],
    }).to_csv(d / "intermittency_custom_LOC.csv", index=False)

    # Station A: mixed flow states
    pd.DataFrame({
        "datetime": ["2020-05-25", "2020-06-25", "2020-07-25", "2020-08-25", "2020-09-25"],
        "value": [5, 4, 3, 1, 2],
    }).to_csv(d / "intermittency_custom_ONDE_A_20200101_20201231_irregular.csv", index=False)

    # Station B: always flowing
    pd.DataFrame({
        "datetime": ["2020-05-25", "2020-06-25", "2020-07-25", "2020-08-25", "2020-09-25"],
        "value": [5, 5, 5, 4, 5],
    }).to_csv(d / "intermittency_custom_ONDE_B_20200101_20201231_irregular.csv", index=False)

    return d


@pytest.mark.fast
class TestIntermittencyConfig:
    def test_hubeau_source_valid(self):
        cfg = IntermittencyConfig(sources=[
            IntermittencySourceConfig(source="hubeau", station_ids=["J0014011"]),
        ], date_start="2020-01-01", date_end="2023-12-31")
        assert cfg.sources[0].source == "hubeau"
        assert cfg.date_start == "2020-01-01"

    def test_custom_source_requires_path(self):
        with pytest.raises(ValueError, match="path"):
            IntermittencySourceConfig(source="custom")

    def test_custom_source_valid(self, tmp_path):
        cfg = IntermittencySourceConfig(source="custom", path=tmp_path)
        assert cfg.path == tmp_path

    def test_invalid_date_order(self):
        with pytest.raises(ValueError, match="date_start must be before"):
            IntermittencyConfig(
                sources=[IntermittencySourceConfig(source="hubeau", extent="watershed")],
                date_start="2023-12-31",
                date_end="2020-01-01",
            )

    def test_invalid_date_format(self):
        with pytest.raises(ValueError, match="Invalid ISO date"):
            IntermittencyConfig(
                sources=[IntermittencySourceConfig(source="hubeau", extent="watershed")],
                date_start="not-a-date",
            )

    def test_data_managers_config_accepts_intermittency(self):
        from hydromodpy.data_managers.data_managers_config import DataManagersConfig
        cfg = DataManagersConfig.model_validate({
            "types": ["intermittency"],
            "intermittency": {
                "sources": [{"source": "hubeau", "extent": "watershed"}],
                "date_start": "2020-01-01",
                "date_end": "2023-12-31",
            },
        })
        assert "intermittency" in cfg.types
        assert cfg.intermittency is not None
        assert len(cfg.intermittency.sources) == 1


@pytest.mark.fast
class TestIntermittencyCustomCSV:
    def test_load_two_stations(self, sample_intermittency_dir):
        cfg = IntermittencySourceConfig(source="custom", path=sample_intermittency_dir)
        records = load_custom(cfg)

        assert len(records) == 2
        ids = {r.station_id for r in records}
        assert ids == {"ONDE_A", "ONDE_B"}

        for r in records:
            assert r.variable == "flow_state"
            assert r.source == "custom"
            assert r.unit == "code"
            assert r.has_data
            assert r.location is not None
            assert r.location.crs == "EPSG:4326"

    def test_flow_codes_clamped(self, sample_intermittency_dir):
        cfg = IntermittencySourceConfig(source="custom", path=sample_intermittency_dir)
        records = load_custom(cfg)
        for r in records:
            values = r.data["value"]
            assert values.min() >= 1
            assert values.max() <= 5

    def test_station_a_has_drought(self, sample_intermittency_dir):
        cfg = IntermittencySourceConfig(source="custom", path=sample_intermittency_dir)
        records = load_custom(cfg)
        rec_a = [r for r in records if r.station_id == "ONDE_A"][0]
        assert 1 in rec_a.data["value"].values  # Assec present

    def test_filter_station_ids(self, sample_intermittency_dir):
        cfg = IntermittencySourceConfig(
            source="custom", path=sample_intermittency_dir, station_ids=["ONDE_B"],
        )
        records = load_custom(cfg)
        assert len(records) == 1
        assert records[0].station_id == "ONDE_B"

    def test_observation_count(self, sample_intermittency_dir):
        cfg = IntermittencySourceConfig(source="custom", path=sample_intermittency_dir)
        records = load_custom(cfg)
        for r in records:
            assert len(r.data) == 5


@pytest.mark.fast
class TestIntermittencyCustomErrors:
    def test_missing_directory(self):
        cfg = IntermittencySourceConfig(source="custom", path=Path("/nonexistent"))
        with pytest.raises(FileNotFoundError):
            load_custom(cfg)

    def test_missing_location_file(self, tmp_path):
        d = tmp_path / "empty"
        d.mkdir()
        cfg = IntermittencySourceConfig(source="custom", path=d)
        with pytest.raises(FileNotFoundError, match="intermittency_custom_LOC"):
            load_custom(cfg)


@pytest.mark.fast
class TestIntermittencyManagerCustom:
    def test_manager_load_result(self, sample_intermittency_dir):
        cfg = IntermittencyConfig(sources=[
            IntermittencySourceConfig(source="custom", path=sample_intermittency_dir),
        ])
        manager = IntermittencyManager(config=cfg, catalog=None, project_period=None)
        result = manager.load()

        assert result.has_points
        assert len(result.points) == 2
        assert all(r.variable == "flow_state" for r in result.points)
