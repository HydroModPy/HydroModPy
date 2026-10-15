"""The site fingerprint is a pure function of the declaration, never of a DEM."""

from __future__ import annotations

import inspect

import pytest

from hydromodpy.core.site import site_fingerprint

NANCON = (389285.910, 6816518.749)


def test_the_same_declaration_gives_the_same_fingerprint() -> None:
    first = site_fingerprint(crs="EPSG:2154", kind="from_outlet_coord", outlet=NANCON)
    second = site_fingerprint(crs="EPSG:2154", kind="from_outlet_coord", outlet=NANCON)
    assert first == second
    assert len(first) == 16
    int(first, 16)


def test_the_dem_resolution_does_not_enter_the_fingerprint() -> None:
    # A run at 25 m and one at 75 m declare the same outlet: one site, two areas.
    # The function reads the declaration only, so it has no way to take the DEM.
    assert set(inspect.signature(site_fingerprint).parameters) == {
        "crs",
        "kind",
        "outlet",
        "polygon_sha256",
    }
    with pytest.raises(TypeError):
        site_fingerprint(  # type: ignore[call-arg]
            crs="EPSG:2154", kind="from_outlet_coord", outlet=NANCON, dem_resolution=75.0
        )
    at_25_m = site_fingerprint(crs="EPSG:2154", kind="from_outlet_coord", outlet=NANCON)
    at_75_m = site_fingerprint(crs="EPSG:2154", kind="from_outlet_coord", outlet=NANCON)
    assert at_25_m == at_75_m


def test_the_outlet_is_rounded_to_the_metre() -> None:
    exact = site_fingerprint(crs="EPSG:2154", kind="from_outlet_coord", outlet=NANCON)
    copied = site_fingerprint(
        crs="EPSG:2154", kind="from_outlet_coord", outlet=(389286.2, 6816518.6)
    )
    moved = site_fingerprint(
        crs="EPSG:2154", kind="from_outlet_coord", outlet=(389287.0, 6816518.749)
    )
    assert exact == copied
    assert exact != moved


def test_the_crs_and_the_kind_enter_the_fingerprint() -> None:
    base = site_fingerprint(crs="EPSG:2154", kind="from_outlet_coord", outlet=NANCON)
    assert base != site_fingerprint(crs="EPSG:3857", kind="from_outlet_coord", outlet=NANCON)
    assert base != site_fingerprint(crs="EPSG:2154", kind="dem", outlet=NANCON)


def test_a_polygon_is_named_by_its_digest() -> None:
    digest = "AB" * 32
    upper = site_fingerprint(crs="EPSG:2154", kind="from_polyg_shp", polygon_sha256=digest)
    lower = site_fingerprint(crs="EPSG:2154", kind="from_polyg_shp", polygon_sha256=digest.lower())
    assert upper == lower


def test_a_declaration_without_outlet_or_polygon_is_refused() -> None:
    with pytest.raises(ValueError, match="outlet or a polygon"):
        site_fingerprint(crs="EPSG:2154", kind="dem")
