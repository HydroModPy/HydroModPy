from __future__ import annotations

from datetime import datetime

import pytest

from hydromodpy.data.contracts.spatial_field import FieldRecord
from hydromodpy.data.variables.dem.config import DemConfig, IgnGeoplateformeDemSource
from hydromodpy.data.variables.hydrometry.config import HydrometryConfig, HydrometrySourceConfig
from hydromodpy.workflow.site_selection_data import (
    default_site_selection_data_root,
    load_dem_path,
    load_hydrometry_records,
)
from tests.unit.site_selection._records import make_point_record


@pytest.mark.fast
def test_load_hydrometry_records_passes_period_from_config_to_loader():
    calls = {}

    def fake_loader(**kwargs):
        calls.update(kwargs)
        return [make_point_record()]

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
        return [make_point_record()]

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


@pytest.mark.fast
def test_load_dem_path_sets_extent_for_geoplateforme_api_source(tmp_path):
    dem_path = tmp_path / "dem.tif"
    dem_path.touch()
    calls = {}

    def fake_loader(**kwargs):
        calls.update(kwargs)
        return [
            FieldRecord(
                variable="dem",
                source="ign_geoplateforme_dem",
                unit="m",
                data=dem_path,
                bbox=kwargs["project_extent"],
                crs="EPSG:2154",
            )
        ]

    cfg = DemConfig(sources=[IgnGeoplateformeDemSource(regions=["Bretagne"])])
    project_extent = (100_000.0, 6_700_000.0, 120_000.0, 6_720_000.0)

    assert load_dem_path(cfg, project_extent=project_extent, loader=fake_loader) == dem_path
    assert calls["config"].sources[0].extent == "study_area"
    assert calls["project_extent"] == project_extent
