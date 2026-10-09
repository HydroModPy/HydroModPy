"""The root [persistence] table is refused with the table to write.

No run read it: the run catalog reads [simulation.results.persistence] and a
calibration reads [calibration.persistence]. A file that set
field_precision = "exact" at the root still stored compact heads.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.config import HydroModPyConfig
from hydromodpy.core.exceptions import ConfigValidationError


def test_a_root_persistence_table_in_a_file_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "project.toml"
    path.write_text(
        '[workspace]\nproject_root = "."\n\n'
        '[workflow]\nmode = "simulation"\n\n'
        '[persistence]\nfield_precision = "exact"\n',
        encoding="utf-8",
    )
    with pytest.raises(ConfigValidationError) as excinfo:
        HydroModPyConfig.from_toml(path)
    message = str(excinfo.value)
    assert "[persistence] is not read" in message
    assert "[simulation.results.persistence]" in message


def test_a_root_persistence_key_in_python_is_refused() -> None:
    with pytest.raises(ValueError, match=r"\[simulation\.results\.persistence\]"):
        HydroModPyConfig.model_validate({"persistence": {"save_zarr": False}})


def test_the_run_persistence_table_is_the_one_read() -> None:
    cfg = HydroModPyConfig.model_validate(
        {
            "workflow": {"mode": "simulation"},
            "geographic": {"source_mode": "synthetic"},
            "simulation": {"results": {"persistence": {"field_precision": "exact"}}},
        }
    )
    assert cfg.simulation.results.persistence.field_precision == "exact"
    assert "persistence" not in HydroModPyConfig.model_fields
