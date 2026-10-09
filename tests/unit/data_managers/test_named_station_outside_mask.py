"""A station named in station_ids survives the watershed mask."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from hydromodpy.data.contracts.location import StationLocation
from hydromodpy.data.variables.piezometry.config import PiezometrySourceConfig
from hydromodpy.data.variables.piezometry.manager import PiezometryManager

from ._test_climatic_managers_builders import _make_point_record


def _mask(tmp_path: Path) -> Path:
    gpd = pytest.importorskip("geopandas")
    from shapely.geometry import box

    path = tmp_path / "watershed.geojson"
    gpd.GeoDataFrame(geometry=[box(-1.3, 48.3, -1.1, 48.4)], crs="EPSG:4326").to_file(path)
    return path


def _record(station_id: str, lon: float, lat: float):
    location = StationLocation(id=station_id, x=lon, y=lat, crs="EPSG:4326")
    return replace(_make_point_record(station_id), location=location)


@pytest.mark.fast
def test_a_named_station_outside_the_mask_is_kept(tmp_path):
    manager = PiezometryManager(config=None, catalog=None)
    source = PiezometrySourceConfig(
        source="hubeau", product="level", station_ids=["FAR"], mask_path=_mask(tmp_path)
    )

    kept = manager._apply_mask([_record("FAR", -1.2, 48.5)], source)

    assert [r.station_id for r in kept] == ["FAR"]


@pytest.mark.fast
def test_a_discovered_station_outside_the_mask_is_dropped(tmp_path):
    manager = PiezometryManager(config=None, catalog=None)
    source = PiezometrySourceConfig(source="hubeau", product="level", mask_path=_mask(tmp_path))

    kept = manager._apply_mask([_record("IN", -1.2, 48.35), _record("FAR", -1.2, 48.5)], source)

    assert [r.station_id for r in kept] == ["IN"]


@pytest.mark.fast
def test_a_dropped_station_is_named_in_a_warning(tmp_path, caplog):
    import logging

    manager = PiezometryManager(config=None, catalog=None)
    source = PiezometrySourceConfig(source="hubeau", product="level", mask_path=_mask(tmp_path))

    with caplog.at_level(logging.WARNING):
        manager._apply_mask([_record("IN", -1.2, 48.35), _record("FAR", -1.2, 48.5)], source)

    assert "outside the mask watershed.geojson dropped: ['FAR']" in caplog.text


@pytest.mark.fast
def test_a_source_whose_every_station_is_outside_is_refused(tmp_path):
    from hydromodpy.core.exceptions import DataSourceError

    manager = PiezometryManager(config=None, catalog=None)
    source = PiezometrySourceConfig(source="hubeau", product="level", mask_path=_mask(tmp_path))

    with pytest.raises(DataSourceError, match=r"every station .* outside the mask.*\['FAR'\]"):
        manager._apply_mask([_record("FAR", -1.2, 48.5)], source)
