"""French departments and regions read from the bundled GeoPackage."""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import pytest

from hydromodpy.spatial.administrative import france
from hydromodpy.spatial.administrative.france import (
    bbox_for_departments,
    bbox_for_regions,
    department_code_to_padded,
    find_departments_in_bbox,
    find_departments_in_regions,
    geometry_for_departments,
    geometry_for_regions,
)
from hydromodpy.spatial.administrative.regions import (
    french_region_code,
    known_french_region_names,
    normalize_french_region_key,
    validate_french_regions,
)

pytestmark = pytest.mark.fast

BRETAGNE = ["022", "029", "035", "056"]


@pytest.fixture(scope="module")
def bundled() -> gpd.GeoDataFrame:
    return gpd.read_file(Path(france.__file__).parent / "departement.gpkg")


@pytest.fixture
def serve(monkeypatch):
    """Make the module read *frame* in place of the bundled GeoPackage."""

    def _serve(frame: gpd.GeoDataFrame) -> None:
        monkeypatch.setattr(france.gpd, "read_file", lambda _path: frame.copy())

    return _serve


def test_french_regions_are_known_by_name_alias_or_code_and_an_unknown_one_lists_them():
    assert {"Auvergne-Rhone-Alpes", "Bretagne", "Ile-de-France", "Guadeloupe", "La-Reunion", "Mayotte"} <= set(known_french_region_names())  # fmt: skip
    assert normalize_french_region_key("La Reunion") == "la-reunion"
    assert [french_region_code(name) for name in ("Auvergne-Rhone-Alpes", "La Reunion", "Reunion")] == ["84", "04", "04"]  # fmt: skip
    assert validate_french_regions(["La Reunion", "84", "Auvergne Rhone Alpes"]) == ["La-Reunion", "Auvergne-Rhone-Alpes"]  # fmt: skip
    for unknown in ("Bretange", "99"):
        with pytest.raises(ValueError, match="Known regions:"):
            french_region_code(unknown)


@pytest.mark.parametrize(
    ("call", "expected"),
    [
        (lambda: find_departments_in_regions(["04"]), ["974"]),
        (lambda: find_departments_in_regions(["Bretagne"]), BRETAGNE),
        (lambda: find_departments_in_bbox((340_000, 6_780_000, 360_000, 6_800_000)), ["035"]),
        *[((lambda raw=raw: department_code_to_padded(raw)), padded) for raw, padded in [("35", "035"), (" 7 ", "007"), ("2a", "02A"), ("02B", "02B"), ("971", "971"), ("x1", "X1")]],
    ],
    ids=["departments_of_la_reunion", "departments_of_bretagne", "a_point_in_rennes_falls_in_ille_et_vilaine", *(f"padded_{c}" for c in ("35", "7", "2a", "02B", "971", "x1"))],
)  # fmt: skip
def test_a_department_is_found_by_region_by_bbox_and_its_code_is_padded(call, expected):
    assert call() == expected


def test_the_bbox_of_a_region_covers_its_departments_and_nothing_less():
    bbox = bbox_for_regions(["Bretagne"])

    assert bbox == bbox_for_departments(BRETAGNE) == bbox_for_departments(["22", "29", "35", "56"])
    assert set(BRETAGNE) <= set(find_departments_in_bbox(bbox))
    for code in BRETAGNE:
        xmin, ymin, xmax, ymax = bbox_for_departments([code])
        assert bbox[0] <= xmin and bbox[1] <= ymin and xmax <= bbox[2] and ymax <= bbox[3]


@pytest.mark.parametrize("margin", [-5.0, 0.0, 1_000.0])
def test_a_margin_grows_the_bbox_on_every_side_and_never_shrinks_it(margin):
    bare = bbox_for_regions(["Bretagne"])
    grown = bbox_for_regions(["Bretagne"], margin_m=margin)

    pad = max(margin, 0.0)
    assert grown == pytest.approx((bare[0] - pad, bare[1] - pad, bare[2] + pad, bare[3] + pad))


def test_the_geometry_of_a_region_is_the_union_of_its_departments():
    region = geometry_for_regions(["Bretagne"])
    parts = [geometry_for_departments([code]) for code in BRETAGNE]

    assert region.bounds == pytest.approx(bbox_for_regions(["Bretagne"]))
    total = sum(part.area for part in parts)
    assert total * (1 - 1e-4) < region.area <= total


def test_a_department_geometry_is_reprojected_to_the_target_crs():
    lonlat = geometry_for_departments(["35"], target_crs="EPSG:4326")
    native = geometry_for_departments(["35"], target_crs=None)

    west, south, east, north = lonlat.bounds
    assert -2.5 < west < east < -1.0 and 47.5 < south < north < 48.8
    assert native.bounds == pytest.approx(bbox_for_departments(["35"]))


@pytest.mark.parametrize(
    ("change", "read", "same"),
    [
        (lambda f: f.to_crs("EPSG:4326"), lambda: bbox_for_departments(["35"]), lambda ref: bbox_for_departments(["35"]) == pytest.approx(ref, abs=1.0)),
        (lambda f: f.set_crs(None, allow_override=True), lambda: geometry_for_departments(["35"]), lambda ref: geometry_for_departments(["35"], target_crs="EPSG:4326").equals(ref)),
        *[(lambda f, c=column: f.rename(columns={"code_insee": c}), lambda: bbox_for_departments(["35"]),
           lambda ref: bbox_for_departments(["35"]) == ref and find_departments_in_bbox(ref)[:1] == ["022"]) for column in ("code", "code_dept", "CODE_DEPT", "INSEE_DEP")],
    ],
    ids=["lon_lat_is_brought_back_to_lambert_93", "without_crs_is_never_reprojected", "code", "code_dept", "CODE_DEPT", "INSEE_DEP"],
)  # fmt: skip
def test_a_frame_in_another_crs_or_with_another_code_column_reads_the_same_departments(bundled, serve, change, read, same):  # fmt: skip
    reference = read()
    serve(change(bundled))

    assert same(reference)


def test_the_union_falls_back_on_unary_union_without_union_all(monkeypatch):
    reference = geometry_for_regions(["Bretagne"])
    monkeypatch.delattr(gpd.base.GeoPandasBase, "union_all")

    with pytest.warns(DeprecationWarning):
        assert geometry_for_regions(["Bretagne"]).equals(reference)


@pytest.mark.parametrize(
    ("change", "call", "match"),
    [
        (lambda f: f.drop(columns="code_insee_de_la_region"), lambda: find_departments_in_regions(["53"]), "region code column"),
        (lambda f: f[f["code_insee_de_la_region"] != "06"], lambda: find_departments_in_regions(["Mayotte"]), "for regions"),
        (lambda f: f, lambda: bbox_for_departments(["999"]), "for codes"),
        (lambda f: f, lambda: geometry_for_departments(["999"]), "for codes"),
        (lambda f: f.drop(columns="code_insee"), lambda: bbox_for_departments(["35"]), "department code column"),
    ],
    ids=["no_region_column", "region_absent", "bbox_unknown_code", "geometry_unknown_code", "no_code_column"],
)  # fmt: skip
def test_refusals(bundled, serve, change, call, match):
    serve(change(bundled))

    with pytest.raises(ValueError, match=match):
        call()
