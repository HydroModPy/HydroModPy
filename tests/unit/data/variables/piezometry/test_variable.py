"""Piezometry stations read from a folder.

A station with a single dated value is a constant head. Heads are stored in m,
and a source in cm is converted.
"""

import pandas as pd
import pytest

from hydromodpy.data.variables.piezometry.config import PiezometrySourceConfig
from hydromodpy.data.variables.piezometry.variable import PiezometryVariable


def single_value_folder(tmp_path, *, unit, value):
    folder = tmp_path / "piezo"
    folder.mkdir()
    pd.DataFrame({"id": ["PZ1"], "x": [0], "y": [0], "crs": ["EPSG:4326"], "unit": [unit]}).to_csv(
        folder / "piezometry_custom_LOC.csv", index=False
    )
    pd.DataFrame({"datetime": ["2020-01-01"], "value": [value]}).to_csv(
        folder / "piezometry_custom_PZ1_20200101_20200331_D.csv", index=False
    )
    return folder


UNITS = [
    pytest.param("m", 10.0, 10.0, id="metres"),
    pytest.param("cm", 250.0, 2.5, id="centimetres"),
]


@pytest.mark.parametrize(("unit", "value", "head_m"), UNITS)
def test_single_value_is_a_constant_head_in_m(tmp_path, project_period, unit, value, head_m):
    folder = single_value_folder(tmp_path, unit=unit, value=value)
    cfg = PiezometrySourceConfig(source="file", path=folder, product=None)

    records = PiezometryVariable(config=None, index=None, project_period=project_period).load_file(
        cfg
    )

    assert len(records) == 1
    assert records[0].is_constant
    assert records[0].data["value"].iloc[0] == pytest.approx(head_m)
    assert records[0].unit == "m"
    assert records[0].source_unit == unit
