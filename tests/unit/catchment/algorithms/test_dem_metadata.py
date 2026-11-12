"""The metadata read off the clipped DEMs: the grid and its WGS 84 corners."""

import socket

import numpy as np
import pytest
import requests

from hydromodpy.catchment.algorithms.dem_metadata import read_dem_metadata
from tests._helpers.geographic_cases import LAMBERT
from tests._helpers.geotiffs import write_geotiff

WEST_OF_GREENWICH = (264_525.0, 6_784_450.0)
"""The north-west corner of a 2 km square in Brittany, centered near 2.83 W, 48.01 N."""


@pytest.fixture
def network_attempts(monkeypatch) -> list[tuple]:
    """Every HTTP request, name lookup and connection of the test, recorded and refused."""
    attempts: list[tuple] = []

    def refuse(*args, **kwargs):
        attempts.append(args)
        raise OSError("no network in this test")

    monkeypatch.setattr(requests.Session, "request", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    monkeypatch.setattr(socket.socket, "connect", refuse)
    return attempts


def _read(tmp_path, *, crs=LAMBERT):
    dem = write_geotiff(
        tmp_path / "dem.tif", np.ones((2, 2), dtype="float32"), origin=WEST_OF_GREENWICH, cell=1e3
    )
    return read_dem_metadata(
        watershed_box_buff_dem_path=dem,
        watershed_buff_dem_path=dem,
        watershed_dem_path=dem,
        crs_project=crs,
    )


def test_long_lat_corners_offline(tmp_path, network_attempts) -> None:
    meta = _read(tmp_path)
    longitude, latitude = meta.centroid_long_lat
    assert longitude == pytest.approx(-2.83, abs=0.01)
    assert latitude == pytest.approx(48.01, abs=0.01)
    assert all(low < high for low, high in zip(meta.ll_long_lat, meta.ur_long_lat, strict=True))
    assert meta.centroid_long_lat_Greenwich == pytest.approx([360.0 + longitude, latitude])
    assert (meta.dx, meta.dy, meta.xmin, meta.ymax) == (1e3, 1e3, *WEST_OF_GREENWICH)
    assert network_attempts == []
    assert "dep_code" not in meta.runtime_attributes()


@pytest.mark.parametrize("crs", [None, "not-a-crs"])
def test_no_crs_no_wgs84_corner(tmp_path, crs) -> None:
    meta = _read(tmp_path, crs=crs)
    assert meta.centroid_long_lat is None
    assert "centroid_long_lat" not in meta.runtime_attributes()
