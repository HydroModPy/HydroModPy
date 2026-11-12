"""Binders that attach loaded data to the domain and the flow after data loading.

Geology and catchment zones become named zones of the domain. The ocean boundary
takes its level in m from the sea-level data."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from hydromodpy.data.contracts.load_result import LoadResult
from hydromodpy.data.contracts.timeseries import PointRecord
from hydromodpy.model.boundaries.climate import apply_oceanic_to_flow
from hydromodpy.model.domain.structure_binders import (
    apply_catchment_zones_to_domain,
    apply_geology_to_domain,
)


class DummyDomain:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def set_zone(self, zone_id: str, zone_obj: object) -> None:
        self.calls.append((zone_id, zone_obj))


def sea_level_point(data: pd.DataFrame, variable: str = "sea_level", **fields) -> PointRecord:
    return PointRecord(
        station_id="station",
        variable=variable,
        unit="m",
        data=data,
        date_start=data["datetime"].min().to_pydatetime(),
        date_end=data["datetime"].max().to_pydatetime(),
        **fields,
    )


def a_constant_level() -> LoadResult:
    data = pd.DataFrame({"datetime": [pd.Timestamp.now()], "value": [7.5]})
    point = sea_level_point(
        data, "mean_sea_level", source="constant", frequency="constant", is_constant=True
    )
    return LoadResult(points=[point])


def an_hourly_level() -> LoadResult:
    data = pd.DataFrame(
        {"datetime": pd.date_range("2003-01-01", periods=3, freq="h"), "value": [1.0, 2.0, 3.0]}
    )
    return LoadResult(points=[sea_level_point(data, source="shom", frequency="H")])


def test_geology_zone() -> None:
    domain = DummyDomain()
    geology = object()

    apply_geology_to_domain(domain=domain, geology=geology)

    assert domain.calls == [("geology", geology)]


def test_catchment_zones(monkeypatch, tmp_path: Path) -> None:
    domain = DummyDomain()
    geographic_dir = tmp_path / "geographic"
    geographic_dir.mkdir()
    names = (
        "watershed.shp",
        "watershed_box_buff.shp",
        "watershed_box_buff_dem.tif",
        "watershed_buff.shp",
    )
    for name in names:
        (geographic_dir / name).write_text("", encoding="utf-8")

    def fake_zone_codes(**_kwargs):
        return SimpleNamespace(
            zone_codes=np.array([[1, 1, 2], [2, 3, 3]], dtype=np.uint8),
            zone_codes_tif=str(geographic_dir / "catchment_zone_codes.tif"),
        )

    monkeypatch.setattr(
        "hydromodpy.model.domain.structure_binders.build_catchment_zone_codes", fake_zone_codes
    )
    geographic = SimpleNamespace(
        watershed_shp=str(geographic_dir / names[0]),
        box_buff=str(geographic_dir / names[1]),
        watershed_box_buff_dem=str(geographic_dir / names[2]),
    )

    apply_catchment_zones_to_domain(domain=domain, geographic=geographic)

    assert len(domain.calls) == 1
    zone_id, zone_obj = domain.calls[0]
    assert zone_id == "catchment"
    assert zone_obj.identifier == "catchment_zones"
    assert zone_obj.shape == (2, 3)
    assert zone_obj.encoded_to_zone == {1: "domain", 2: "buffer", 3: "core"}


def test_catchment_zones_skipped_without_artifacts() -> None:
    domain = DummyDomain()
    geographic = SimpleNamespace(
        watershed_shp="missing/watershed.shp",
        box_buff="missing/watershed_box_buff.shp",
        watershed_box_buff_dem="missing/watershed_box_buff_dem.tif",
    )

    apply_catchment_zones_to_domain(domain=domain, geographic=geographic)

    assert domain.calls == []


OCEAN_LEVELS = [
    pytest.param(a_constant_level(), 7.5, id="constant level"),
    pytest.param(an_hourly_level(), 2.0, id="mean of a series"),
]


@pytest.mark.parametrize(("oceanic", "level_m"), OCEAN_LEVELS)
def test_ocean_boundary_level(oceanic, level_m) -> None:
    flow = SimpleNamespace(boundary_conditions={"ocean": SimpleNamespace(value=None)})

    apply_oceanic_to_flow(flow=flow, oceanic=oceanic)

    assert flow.boundary_conditions["ocean"].value == pytest.approx(level_m)


def test_ocean_level_skipped_without_ocean_boundary() -> None:
    flow = SimpleNamespace(boundary_conditions={})

    apply_oceanic_to_flow(flow=flow, oceanic=LoadResult(points=[]))

    assert flow.boundary_conditions == {}
