"""The metadata read off the clipped DEMs: the grid, its WGS 84 corners and the department."""

import geopy.geocoders
import numpy as np
import pytest
from geopy.exc import GeocoderServiceError, GeocoderUnavailable

from hydromodpy.spatial.geographic.dem_metadata import read_dem_metadata
from tests._helpers.geographic_cases import LAMBERT
from tests._helpers.geotiffs import write_geotiff

WEST_OF_GREENWICH = (264_525.0, 6_784_450.0)
"""The north-west corner of a 2 km square in Brittany, centred near 2.83 W, 48.01 N."""


class _Locator:
    """A Nominatim double that answers *answers* in turn, raising the exceptions."""

    queries: list[str] = []
    answers: list[object] = []

    def __init__(self, *args, **kwargs) -> None:
        pass

    def reverse(self, query, **kwargs):
        self.queries.append(query)
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return type("Location", (), {"address": answer})()


def _read(tmp_path, *, answers=(), crs=LAMBERT):
    dem = write_geotiff(
        tmp_path / "dem.tif", np.ones((2, 2), dtype="float32"), origin=WEST_OF_GREENWICH, cell=1e3
    )
    _Locator.queries, _Locator.answers = [], list(answers)
    return read_dem_metadata(
        watershed_box_buff_dem_path=dem,
        watershed_buff_dem_path=dem,
        watershed_dem_path=dem,
        crs_project=crs,
        locator_factory=_Locator,
    )


def test_every_long_lat_is_longitude_then_latitude_and_the_geocoder_gets_the_reverse(tmp_path):
    meta = _read(tmp_path, answers=["Naizin, Morbihan, 56500, France"])
    longitude, latitude = meta.centroid_long_lat
    assert longitude == pytest.approx(-2.83, abs=0.01)
    assert latitude == pytest.approx(48.01, abs=0.01)
    assert all(low < high for low, high in zip(meta.ll_long_lat, meta.ur_long_lat, strict=True))
    assert meta.centroid_long_lat_Greenwich == pytest.approx([360.0 + longitude, latitude])
    assert _Locator.queries == [f"{latitude}, {longitude}"]
    assert meta.dep_code == 56
    assert (meta.dx, meta.dy, meta.xmin, meta.ymax) == (1e3, 1e3, *WEST_OF_GREENWICH)
    assert meta.runtime_attributes()["dep_code"] == 56


@pytest.mark.parametrize(
    "answers",
    [
        pytest.param([GeocoderUnavailable("offline")], id="unavailable"),
        pytest.param([ValueError("no answer")], id="any-failure"),
        pytest.param([GeocoderServiceError("quota")], id="service-error"),
        pytest.param([OSError("certificate"), OSError("still no")], id="ssl-retry-fails"),
        pytest.param(["an address without a postcode"], id="no-postcode"),
    ],
)
def test_the_department_is_best_effort_and_never_fails_an_offline_run(tmp_path, answers) -> None:
    assert _read(tmp_path, answers=answers).dep_code is None


def test_a_certificate_failure_is_retried_with_the_certifi_bundle(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(geopy.geocoders.options, "default_ssl_context", None)
    meta = _read(tmp_path, answers=[OSError("certificate"), "Rennes, 35000, France"])
    assert meta.dep_code == 35
    assert geopy.geocoders.options.default_ssl_context is not None


@pytest.mark.parametrize("crs", [None, "not-a-crs"])
def test_without_a_usable_crs_there_is_no_wgs84_corner_and_no_department(tmp_path, crs) -> None:
    meta = _read(tmp_path, crs=crs)
    assert meta.centroid_long_lat is None
    assert meta.dep_code is None
    assert _Locator.queries == []
    assert "dep_code" not in meta.runtime_attributes()
