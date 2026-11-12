from __future__ import annotations

import json
from pathlib import Path

import pytest

from hydromodpy.config.hydromodpy_config import HydroModPyConfig
from hydromodpy.core.exceptions import ConfigValidationError


def test_hydromodpy_config_from_json_resolves_nested_geographic_catchment(
    tmp_path: Path,
) -> None:
    dem_path = tmp_path / "dem.tif"
    dem_path.touch()
    payload = {
        "workflow": {"mode": "simulation"},
        "workspace": {"root": str(tmp_path)},
        "site": {"name": "site_a"},
        "geographic": {"catchment": {"kind": "dem"}},
        "data": {"dem": {"sources": [{"source": "file", "path": "dem.tif"}]}},
    }

    cfg = HydroModPyConfig.from_json(json.dumps(payload), base_dir=tmp_path)

    assert cfg.data.dem.sources[0].path == dem_path.resolve()
