"""Completeness report of a station variable: expected and missing days over the project period."""

import pandas as pd
import pytest

from hydromodpy.data.contracts.timeseries import PointRecord
from hydromodpy.data.families.stations import StationVariable
from hydromodpy.data.variables.hydrometry.config import HydrometryConfig, HydrometrySourceConfig
from hydromodpy.data.variables.hydrometry.variable import HydrometryVariable


def test_report_of_two_complete_stations(sample_hydro_dir, project_period):
    config = HydrometryConfig(
        sources=[HydrometrySourceConfig(source="file", path=sample_hydro_dir)]
    )
    variable = HydrometryVariable(config=config, index=None, project_period=project_period)

    report = variable.get_completeness_report(variable.load())

    assert len(report) == 2
    assert {"station_id", "completeness_pct", "variable", "source"} <= set(report.columns)
    # Both stations have full data (91 days).
    for _, row in report.iterrows():
        assert row["completeness_pct"] == pytest.approx(100.0)
        assert row["expected_days"] == 91
        assert row["missing_days"] == 0


def test_a_constant_record_is_complete(project_period):
    record = PointRecord(
        station_id="C1",
        variable="discharge",
        source="file",
        unit="m3/s",
        frequency="D",
        data=pd.DataFrame(
            {
                "datetime": pd.date_range(project_period[0], project_period[1], freq="D"),
                "value": 1.0,
            }
        ),
        date_start=project_period[0],
        date_end=project_period[1],
        is_constant=True,
    )

    class DummyVariable(StationVariable):
        VARIABLE_NAME = "test"

        def _fetch_from_source(self, source_cfg):
            return []

    variable = DummyVariable(
        config=type("C", (), {"sources": []})(), index=None, project_period=project_period
    )
    report = variable.get_completeness_report([record])

    assert bool(report.iloc[0]["is_constant"]) is True
    assert report.iloc[0]["completeness_pct"] == pytest.approx(100.0)
