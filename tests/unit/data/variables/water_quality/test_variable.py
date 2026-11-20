"""Water quality stations read from a folder.

A station with a single dated value is a constant concentration. Concentrations
are stored in mg/L, and a source in ug/l is converted.
"""

import pandas as pd
import pytest

from hydromodpy.data.variables.water_quality.config import WaterQualitySourceConfig
from hydromodpy.data.variables.water_quality.variable import WaterQualityVariable


def load_file(cfg, project_period):
    return WaterQualityVariable(config=None, index=None, project_period=project_period).load_file(
        cfg
    )


def test_station_ids_filter_the_records(sample_wq_dir, project_period):
    cfg = WaterQualitySourceConfig(source="file", path=sample_wq_dir, station_ids=["SITE02"])

    records = load_file(cfg, project_period)

    assert [record.station_id for record in records] == ["SITE02"]


def single_value_folder(tmp_path, *, unit, value):
    folder = tmp_path / "wq"
    folder.mkdir()
    pd.DataFrame(
        {"id": ["S1"], "x": [2.35], "y": [48.85], "crs": ["EPSG:4326"], "unit": [unit]}
    ).to_csv(folder / "waterquality_custom_LOC.csv", index=False)
    pd.DataFrame({"datetime": ["2020-01-01"], "value": [value]}).to_csv(
        folder / "waterquality_custom_S1_20200101_20200331_D.csv", index=False
    )
    return folder


UNITS = [
    pytest.param("mg/L", 7.0, 7.0, id="mg per litre"),
    pytest.param("ug/l", 2500.0, 2.5, id="ug per litre"),
]


@pytest.mark.parametrize(("unit", "value", "mg_l"), UNITS)
def test_single_value_is_a_constant_in_mg_l(tmp_path, project_period, unit, value, mg_l):
    cfg = WaterQualitySourceConfig(
        source="file", path=single_value_folder(tmp_path, unit=unit, value=value)
    )

    records = load_file(cfg, project_period)

    assert len(records) == 1
    assert records[0].is_constant
    assert records[0].data["value"].iloc[0] == pytest.approx(mg_l)
    assert records[0].unit == "mg/L"
    assert records[0].source_unit == unit
