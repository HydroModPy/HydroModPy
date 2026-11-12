"""Unit tests for oceanic custom loader dispatch."""

from pathlib import Path

import pytest

from hydromodpy.data.variables.oceanic.config import OceanicSourceConfig
from hydromodpy.data.variables.oceanic.variable import OceanicVariable


def _load_file(cfg, *, project_period=None):
    """Load one custom source the way the oceanic manager does."""
    return OceanicVariable(config=None, index=None, project_period=project_period).load_file(cfg)


@pytest.mark.fast
class TestLoadCustomDispatch:
    def test_unsupported_extension_raises(self, tmp_path):
        bad_file = tmp_path / "data.xyz"
        bad_file.write_text("hello")
        cfg = OceanicSourceConfig(source="file", path=bad_file)
        with pytest.raises(ValueError, match="Unsupported custom format"):
            _load_file(cfg)

    def test_missing_directory_raises(self, tmp_path):
        cfg = OceanicSourceConfig(source="file", path=tmp_path / "nonexistent")
        with pytest.raises((FileNotFoundError, ValueError)):
            _load_file(cfg)

    def test_csv_directory_without_loc_file_raises(self, tmp_path):
        data_dir = tmp_path / "oceanic"
        data_dir.mkdir()
        cfg = OceanicSourceConfig(source="file", path=data_dir)
        with pytest.raises(FileNotFoundError, match="No oceanic_file_LOC"):
            _load_file(cfg)
