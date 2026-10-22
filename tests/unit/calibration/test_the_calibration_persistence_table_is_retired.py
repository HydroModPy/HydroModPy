"""``[calibration.persistence]`` is retired: nothing ever read it.

The run a calibration promotes follows ``[simulation.results.persistence]``,
and the session writes its journal whatever the table says. The table loads
with a warning, so the configuration frozen by an earlier session, which spells
out every default, still reads back, and the schema no longer offers it.
"""

from __future__ import annotations

import pytest

from hydromodpy.calibration.config import CalibrationConfig

pytestmark = pytest.mark.unit

SECTION = {"parameters": {"K": {"bounds": [1e-7, 1e-3]}}}


def test_the_table_loads_with_a_warning_and_is_dropped() -> None:
    with pytest.warns(DeprecationWarning, match="persistence"):
        cfg = CalibrationConfig.model_validate({**SECTION, "persistence": {"save_zarr": False}})

    assert "persistence" not in cfg.model_dump()


def test_the_schema_no_longer_offers_it() -> None:
    assert "persistence" not in CalibrationConfig.model_json_schema()["properties"]
