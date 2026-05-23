from __future__ import annotations

from datetime import datetime

import pandas as pd
import pytest

from hydromodpy.data.contracts.location import StationLocation
from hydromodpy.data.contracts.timeseries import PointRecord
from hydromodpy.data.variables.hydrometry.config import HydrometryConfig, HydrometrySourceConfig
from hydromodpy.workflow.site_selection_data import (
    default_site_selection_data_root,
    load_hydrometry_records,
)


def _record() -> PointRecord:
    return PointRecord(
        station_id="J123456701",
        variable="discharge",
        source="hubeau",
        unit="m3/s",
        frequency="D",
        data=pd.DataFrame({"datetime": ["2020-01-01"], "value": [1.0]}),
        date_start=datetime(2020, 1, 1),
        date_end=datetime(2020, 1, 1),
        location=StationLocation("J123456701", 0.0, 0.0, "EPSG:2154"),
    )


@pytest.mark.fast
def test_load_hydrometry_records_passes_period_from_config_to_loader():
    calls = {}

    def fake_loader(**kwargs):
        calls.update(kwargs)
        return [_record()]

    cfg = HydrometryConfig(
        date_start="2020-01-01",
        date_end="2020-01-10",
        sources=[HydrometrySourceConfig(source="hubeau", product="QmnJ")],
    )

    records = load_hydrometry_records(cfg, loader=fake_loader)

    assert len(records) == 1
    assert calls["project_period"] == (datetime(2020, 1, 1), datetime(2020, 1, 10))
    assert calls["config"] is cfg


@pytest.mark.fast
def test_load_hydrometry_records_prefers_explicit_project_period():
    explicit = (datetime(2021, 1, 1), datetime(2021, 1, 2))
    calls = {}

    def fake_loader(**kwargs):
        calls.update(kwargs)
        return [_record()]

    cfg = HydrometryConfig(
        date_start="2020-01-01",
        date_end="2020-01-10",
        sources=[HydrometrySourceConfig(source="hubeau", product="QmnJ")],
    )

    load_hydrometry_records(cfg, project_period=explicit, loader=fake_loader)

    assert calls["project_period"] == explicit


@pytest.mark.fast
def test_default_site_selection_data_root_uses_workspace_env(monkeypatch, tmp_path):
    workspace = tmp_path / "workspace"
    monkeypatch.setenv("HYDROMODPY_WORKSPACE", str(workspace))

    assert default_site_selection_data_root() == (workspace / "data").resolve()
