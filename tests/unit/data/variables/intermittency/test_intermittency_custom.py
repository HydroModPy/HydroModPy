"""Tests for intermittency custom loader and config validation."""

from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest

from hydromodpy.data.variables.intermittency.config import IntermittencySourceConfig
from hydromodpy.data.variables.intermittency.variable import IntermittencyVariable


def _load_file(cfg, *, project_period=None):
    """Load one custom source the way the intermittency manager does."""
    return IntermittencyVariable(config=None, index=None, project_period=project_period).load_file(
        cfg
    )


@pytest.fixture
def sample_intermittency_dir(tmp_path):
    """Temporary directory with intermittency custom files (LOC + 2 chronicles)."""
    d = tmp_path / "intermittency"
    d.mkdir()

    pd.DataFrame(
        {
            "id": ["ONDE_A", "ONDE_B"],
            "x": [-1.5, -1.6],
            "y": [48.1, 48.2],
            "crs": ["EPSG:4326", "EPSG:4326"],
        }
    ).to_csv(d / "intermittency_custom_LOC.csv", index=False)

    # Station A: mixed flow states
    pd.DataFrame(
        {
            "datetime": ["2020-05-25", "2020-06-25", "2020-07-25", "2020-08-25", "2020-09-25"],
            "value": [5, 4, 3, 1, 2],
        }
    ).to_csv(d / "intermittency_custom_ONDE_A_20200101_20201231_irregular.csv", index=False)

    # Station B: always flowing
    pd.DataFrame(
        {
            "datetime": ["2020-05-25", "2020-06-25", "2020-07-25", "2020-08-25", "2020-09-25"],
            "value": [5, 5, 5, 4, 5],
        }
    ).to_csv(d / "intermittency_custom_ONDE_B_20200101_20201231_irregular.csv", index=False)

    return d


@pytest.mark.fast
class TestIntermittencyConfig:
    def test_custom_source_requires_path(self):
        with pytest.raises(ValueError, match="path"):
            IntermittencySourceConfig(source="file")


@pytest.mark.fast
class TestIntermittencyCustomCSV:
    def test_station_a_has_drought(self, sample_intermittency_dir):
        cfg = IntermittencySourceConfig(source="file", path=sample_intermittency_dir)
        records = _load_file(cfg)
        rec_a = [r for r in records if r.station_id == "ONDE_A"][0]
        assert 1 in rec_a.data["value"].values  # Assec present


@pytest.mark.fast
class TestIntermittencyCustomErrors:
    def test_missing_directory(self):
        cfg = IntermittencySourceConfig(source="file", path=Path("/nonexistent"))
        with pytest.raises(FileNotFoundError):
            _load_file(cfg)

    def test_missing_location_file(self, tmp_path):
        d = tmp_path / "empty"
        d.mkdir()
        cfg = IntermittencySourceConfig(source="file", path=d)
        with pytest.raises(FileNotFoundError, match="intermittency_custom_LOC"):
            _load_file(cfg)


@pytest.mark.fast
class TestIntermittencyStationRequest:
    def test_code_departement_alone_resolves_to_department_extent(self, tmp_path):
        cfg = IntermittencySourceConfig(source="hubeau", code_departement=["35"])
        manager = IntermittencyVariable(config=None, index=None, project_extent=None)
        req = manager._station_request(
            cfg,
            out_dir=tmp_path,
            station_ids=(),
            bbox=None,
            start=datetime(2020, 1, 1),
            end=datetime(2020, 1, 31),
        )
        assert req.extent is not None
        assert req.extent.crs == "EPSG:4326"
        assert req.station_ids == ()
        assert -2.5 < req.extent.xmin < -1.5
        assert 47.5 < req.extent.ymin < 48.5
