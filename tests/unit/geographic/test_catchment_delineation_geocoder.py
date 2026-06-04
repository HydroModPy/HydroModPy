"""Tests for the best-effort department geocoding used by ``CatchmentDelineation``."""

from __future__ import annotations

from geopy.exc import GeocoderUnavailable

from hydromodpy.spatial.geographic.dem_metadata import _resolve_dep_code


class _UnavailableNominatim:
    def __init__(self, *args, **kwargs):
        pass

    def reverse(self, *_args, **_kwargs):
        raise GeocoderUnavailable("offline")


def test_resolve_dep_code_returns_none_when_geocoder_is_unavailable() -> None:
    """Department lookup is best-effort and should not fail offline runs."""
    assert (
        _resolve_dep_code(
            centroid_long_lat_Greenwich=[48.019638516018894, -2.8265621461935666],
            locator_factory=_UnavailableNominatim,
        )
        is None
    )
