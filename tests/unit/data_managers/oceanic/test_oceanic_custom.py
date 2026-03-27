"""Unit tests for oceanic custom loader dispatch."""

from pathlib import Path

import pytest

from hydromodpy.data.variables.oceanic.config import OceanicSourceConfig
from hydromodpy.data.variables.oceanic.custom import load_custom


@pytest.mark.fast
class TestLoadCustomDispatch:
    def test_unsupported_extension_raises(self, tmp_path):
        bad_file = tmp_path / "data.xyz"
        bad_file.write_text("hello")
        cfg = OceanicSourceConfig(source="custom", path=bad_file)
        with pytest.raises(ValueError, match="Unsupported custom format"):
            load_custom(cfg)

    def test_missing_directory_raises(self, tmp_path):
        cfg = OceanicSourceConfig(source="custom", path=tmp_path / "nonexistent")
        with pytest.raises((FileNotFoundError, ValueError)):
            load_custom(cfg)

    def test_csv_directory_without_loc_file_raises(self, tmp_path):
        data_dir = tmp_path / "oceanic"
        data_dir.mkdir()
        cfg = OceanicSourceConfig(source="custom", path=data_dir)
        with pytest.raises(FileNotFoundError, match="No oceanic_custom_LOC"):
            load_custom(cfg)

    def test_csv_directory_with_loc_and_chronicle(self, tmp_path):
        data_dir = tmp_path / "oceanic"
        data_dir.mkdir()

        loc_file = data_dir / "oceanic_custom_LOC.csv"
        loc_file.write_text("id,x,y,crs,unit\nST01,-1.5,48.0,EPSG:4326,m\n")

        chronicle = data_dir / "oceanic_custom_ST01_20030101_20030110_D.csv"
        chronicle.write_text("datetime,value\n2003-01-01,0.5\n2003-01-02,0.6\n")

        cfg = OceanicSourceConfig(source="custom", path=data_dir)
        records = load_custom(cfg)
        assert len(records) == 1
        rec = records[0]
        assert rec.station_id == "ST01"
        assert rec.variable == "oceanic"
        assert rec.unit == "m"
        assert len(rec.data) == 2
