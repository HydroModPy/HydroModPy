"""Check a delineated catchment against the area its gauge publishes.

Distance to the station cannot see an outlet placed on the wrong branch of a
confluence. Area can: two points forty metres apart on two different streams
close catchments that differ by an order of magnitude.
"""

from __future__ import annotations

import pytest

from hydromodpy.data.variables.hydrometry import catchment_area_check as mod
from hydromodpy.data.variables.hydrometry.catchment_area_check import (
    compare_catchment_area,
    published_catchment_area_km2,
    site_id_of_station,
)

_NANCON_STATION = "J001401001"
_NANCON_SITE = "J0014010"
_NANCON_AREA_KM2 = 64.45


def _payload(area) -> dict:
    return {"data": [{"code_site": _NANCON_SITE, "surface_bv": area}]}


def test_a_station_code_carries_its_site_code():
    assert site_id_of_station(_NANCON_STATION) == _NANCON_SITE


def test_a_site_code_is_returned_unchanged():
    assert site_id_of_station(_NANCON_SITE) == _NANCON_SITE


def test_the_published_area_is_read_from_the_site_endpoint(monkeypatch):
    seen: dict = {}

    def _get_json(url, params=None, **kwargs):
        del kwargs
        seen["url"] = url
        seen["params"] = params
        return _payload(_NANCON_AREA_KM2)

    monkeypatch.setattr("hydromodpy.data.common.api_client.get_json", _get_json)

    assert published_catchment_area_km2(_NANCON_STATION) == pytest.approx(_NANCON_AREA_KM2)
    assert seen["url"].endswith("/referentiel/sites")
    assert seen["params"]["code_site"] == _NANCON_SITE


@pytest.mark.parametrize(
    "payload", [{"data": []}, {}, _payload(None), _payload("abc"), _payload(0)]
)
def test_a_site_without_a_usable_area_yields_nothing(monkeypatch, payload):
    monkeypatch.setattr("hydromodpy.data.common.api_client.get_json", lambda *a, **k: payload)

    assert published_catchment_area_km2(_NANCON_STATION) is None


def test_an_unreachable_service_yields_nothing_rather_than_failing(monkeypatch):
    """A cross-check that cannot run must never take the run down with it."""

    def _boom(*args, **kwargs):
        raise OSError("network down")

    monkeypatch.setattr("hydromodpy.data.common.api_client.get_json", _boom)

    assert published_catchment_area_km2(_NANCON_STATION) is None


def test_an_agreeing_area_does_not_warn(monkeypatch, caplog):
    """The measured Nancon case: 64.61 km2 delineated against 64.45 published."""
    monkeypatch.setattr(mod, "published_catchment_area_km2", lambda _sid: _NANCON_AREA_KM2)

    with caplog.at_level("WARNING"):
        comparison = compare_catchment_area(_NANCON_STATION, 64.61)

    assert comparison is not None
    assert comparison.relative_gap == pytest.approx(0.0025, abs=1e-4)
    assert not caplog.text


def test_a_catchment_on_the_wrong_branch_warns(monkeypatch, caplog):
    monkeypatch.setattr(mod, "published_catchment_area_km2", lambda _sid: _NANCON_AREA_KM2)

    with caplog.at_level("WARNING"):
        comparison = compare_catchment_area(_NANCON_STATION, 6.0)

    assert comparison is not None
    assert "wrong branch of a confluence" in caplog.text
    assert "6.00 km2 delineated against 64.45 km2 published" in str(comparison)


def test_the_warning_threshold_is_the_caller_s_to_set(monkeypatch, caplog):
    monkeypatch.setattr(mod, "published_catchment_area_km2", lambda _sid: 100.0)

    with caplog.at_level("WARNING"):
        compare_catchment_area(_NANCON_STATION, 105.0, warn_relative_gap=0.20)

    assert not caplog.text


def test_no_published_area_is_not_a_failure(monkeypatch):
    monkeypatch.setattr(mod, "published_catchment_area_km2", lambda _sid: None)

    assert compare_catchment_area(_NANCON_STATION, 64.61) is None


def test_a_delineated_area_of_zero_is_refused():
    with pytest.raises(ValueError, match="must be positive"):
        compare_catchment_area(_NANCON_STATION, 0.0)
