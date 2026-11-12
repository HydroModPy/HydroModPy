"""Check a delineated catchment against the area its gauge publishes.

Distance to the station cannot see an outlet placed on the wrong branch of a
confluence. Area can: two points forty meters apart on two different streams
close catchments that differ by an order of magnitude.
"""

from __future__ import annotations

import pytest

from hydromodpy.core.io.fetch import HTTPClient
from hydromodpy.data.variables.hydrometry import catchment_area_check as mod
from hydromodpy.data.variables.hydrometry.catchment_area_check import (
    compare_catchment_area,
    published_catchment_area_km2,
)

_NANCON_STATION = "J001401001"
_NANCON_SITE = "J0014010"
_NANCON_AREA_KM2 = 64.45


def _payload(area) -> dict:
    return {"data": [{"code_site": _NANCON_SITE, "surface_bv": area}]}


def test_published_area_from_site_endpoint(monkeypatch):
    seen: dict = {}

    def _get_json(_client, url, params=None, **kwargs):
        del kwargs
        seen["url"] = url
        seen["params"] = params
        return _payload(_NANCON_AREA_KM2)

    monkeypatch.setattr("hydromodpy.data.common.api_client.get_json", _get_json)

    assert published_catchment_area_km2(_NANCON_STATION, client=HTTPClient()) == pytest.approx(
        _NANCON_AREA_KM2
    )
    assert seen["url"].endswith("/referentiel/sites")
    assert seen["params"]["code_site"] == _NANCON_SITE


@pytest.mark.parametrize(
    "payload", [{"data": []}, {}, _payload(None), _payload("abc"), _payload(0)]
)
def test_site_without_usable_area(monkeypatch, payload):
    monkeypatch.setattr("hydromodpy.data.common.api_client.get_json", lambda *a, **k: payload)

    assert published_catchment_area_km2(_NANCON_STATION, client=HTTPClient()) is None


def test_unreachable_service(monkeypatch):
    # A cross-check that cannot run must never take the run down with it.

    def _boom(*args, **kwargs):
        raise OSError("network down")

    monkeypatch.setattr("hydromodpy.data.common.api_client.get_json", _boom)

    assert published_catchment_area_km2(_NANCON_STATION, client=HTTPClient()) is None


def test_agreeing_area_does_not_warn(monkeypatch, caplog):
    # The measured Nancon case: 64.61 km2 delineated against 64.45 published.
    monkeypatch.setattr(mod, "published_catchment_area_km2", lambda _sid, **_kw: _NANCON_AREA_KM2)

    with caplog.at_level("WARNING"):
        comparison = compare_catchment_area(_NANCON_STATION, 64.61, client=HTTPClient())

    assert comparison is not None
    assert comparison.relative_gap == pytest.approx(0.0025, abs=1e-4)
    assert not caplog.text


def test_no_published_area(monkeypatch):
    monkeypatch.setattr(mod, "published_catchment_area_km2", lambda _sid, **_kw: None)

    assert compare_catchment_area(_NANCON_STATION, 64.61, client=HTTPClient()) is None


def test_zero_area_is_refused():
    with pytest.raises(ValueError, match="must be positive"):
        compare_catchment_area(_NANCON_STATION, 0.0, client=HTTPClient())
