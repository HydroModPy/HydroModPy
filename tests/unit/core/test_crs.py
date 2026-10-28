"""The CRS helpers of ``core``: the stamp on a producer's output, and the frame of an overlay.

``ensure_crs`` stamps a producer's own output, and nothing else. The helper
moved here from ``spatial.geographic.geographic_io`` so that a terrain engine
can stamp what it writes without importing a sibling package. The raster
branch had no test before that move; it has one now, because the whole point
of the function is that it rewrites metadata and not pixels.

``to_mesh_crs`` brings a vector layer into the frame of a mesh before an
overlay. A mesh stores bare coordinates, so both frames are named by the
caller and a missing one is refused rather than guessed.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pytest
import rasterio
from pyproj import CRS, Transformer
from rasterio.transform import from_origin
from shapely.geometry import LineString, Point

from hydromodpy.core.io import crs as crs_io


def _write_tif_without_crs(path: Path) -> np.ndarray:
    values = np.arange(12, dtype="float32").reshape(3, 4)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=3,
        width=4,
        count=1,
        dtype="float32",
        transform=from_origin(0.0, 75.0, 25.0, 25.0),
        nodata=-9999.0,
    ) as dst:
        dst.write(values, 1)
    return values


def test_the_shapefile_branch_writes_a_prj_without_reopening_the_vector(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    shp_path = tmp_path / "domain.shp"
    shp_path.write_text("", encoding="utf-8")

    monkeypatch.setattr(
        crs_io.gpd,
        "read_file",
        lambda *_args, **_kwargs: pytest.fail("shapefile should not be reopened"),
    )

    crs_io.ensure_crs(shp_path, "EPSG:2154")

    expected_wkt = CRS.from_user_input("EPSG:2154").to_wkt(version="WKT1_ESRI")
    assert shp_path.with_suffix(".prj").read_text(encoding="utf-8") == expected_wkt


def test_a_missing_shapefile_is_named_in_the_refusal(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="Shapefile not found"):
        crs_io.ensure_crs(tmp_path / "missing.shp", "EPSG:2154")


def test_the_raster_branch_declares_the_crs_and_leaves_the_band_alone(tmp_path: Path) -> None:
    tif_path = tmp_path / "accumulation.tif"
    values = _write_tif_without_crs(tif_path)
    with rasterio.open(tif_path) as src:
        assert src.crs is None
        before = hashlib.sha256(src.read(1).tobytes()).hexdigest()

    crs_io.ensure_crs(tif_path, "EPSG:2154")

    with rasterio.open(tif_path) as src:
        assert src.crs == rasterio.crs.CRS.from_user_input("EPSG:2154")
        assert hashlib.sha256(src.read(1).tobytes()).hexdigest() == before
        assert src.nodata == -9999.0
        np.testing.assert_array_equal(src.read(1), values)


def test_declaring_nothing_leaves_the_file_untouched(tmp_path: Path) -> None:
    """A caller with no CRS to declare is not a caller in error."""
    tif_path = tmp_path / "accumulation.tif"
    _write_tif_without_crs(tif_path)
    before = tif_path.read_bytes()

    crs_io.ensure_crs(tif_path, None)
    crs_io.ensure_crs(tmp_path / "missing.shp", None)

    assert tif_path.read_bytes() == before


# -- the frame of an overlay ---------------------------------------------------

LAMBERT93 = "EPSG:2154"


def test_a_layer_in_another_frame_comes_back_in_the_mesh_frame() -> None:
    line = LineString([(-1.68, 48.11), (-1.67, 48.12)])

    (projected,) = crs_io.to_mesh_crs([line], mesh_crs=LAMBERT93, geometry_crs="EPSG:4326")

    to_lambert = Transformer.from_crs("EPSG:4326", LAMBERT93, always_xy=True)
    expected = np.column_stack(to_lambert.transform(*np.asarray(line.coords).T))
    np.testing.assert_allclose(np.asarray(projected.coords), expected)


def test_a_layer_already_in_the_mesh_frame_comes_back_as_it_is() -> None:
    line = LineString([(350_000.0, 6_790_000.0), (350_100.0, 6_790_000.0)])

    parts = crs_io.to_mesh_crs([line], mesh_crs=LAMBERT93, geometry_crs=CRS.from_epsg(2154))

    assert len(parts) == 1
    assert parts[0] is line


def test_missing_and_empty_geometries_are_left_out() -> None:
    point = Point(350_000.0, 6_790_000.0)

    parts = crs_io.to_mesh_crs(
        [None, LineString(), point], mesh_crs=LAMBERT93, geometry_crs=LAMBERT93
    )
    nothing = crs_io.to_mesh_crs([None, LineString()], mesh_crs=LAMBERT93, geometry_crs="EPSG:4326")

    assert parts == [point]
    assert nothing == []


@pytest.mark.parametrize("missing", ["mesh_crs", "geometry_crs"])
@pytest.mark.parametrize("value", [None, "", "   "], ids=["none", "empty", "blank"])
def test_a_missing_frame_is_refused_by_name(missing: str, value: str | None) -> None:
    frames = {"mesh_crs": LAMBERT93, "geometry_crs": LAMBERT93, missing: value}

    with pytest.raises(ValueError, match=f"explicit {missing}"):
        crs_io.to_mesh_crs([Point(0.0, 0.0)], **frames)


@pytest.mark.parametrize(
    "crs_like", [2154, "EPSG:2154", CRS.from_epsg(2154)], ids=["int", "str", "crs"]
)
def test_a_crs_is_read_from_a_code_a_string_or_a_crs(crs_like: crs_io.CrsLike) -> None:
    assert crs_io.require_crs(crs_like, "mesh_crs") == CRS.from_epsg(2154)


@pytest.mark.parametrize(
    ("left", "right", "same"),
    [
        ("EPSG:2154", " epsg:2154", True),
        ("EPSG:4326", "WGS84", True),
        ("EPSG:2154", "EPSG:4326", False),
        ("EPSG:2154", "not a crs", False),
    ],
    ids=["label", "parsed", "other", "unreadable"],
)
def test_two_labels_name_the_same_frame_only_when_pyproj_agrees(
    left: str, right: str, same: bool
) -> None:
    assert crs_io.same_crs(left, right) is same


def test_a_raster_crs_reads_as_text_and_its_absence_as_none(tmp_path: Path) -> None:
    path = tmp_path / "bare.tif"
    _write_tif_without_crs(path)
    with rasterio.open(path) as src:
        assert crs_io.crs_text(src.crs) is None
    crs_io.ensure_crs(path, "EPSG:2154")
    with rasterio.open(path) as src:
        assert crs_io.crs_text(src.crs) == "EPSG:2154"


def test_one_degree_of_the_equator_is_a_great_circle_arc() -> None:
    assert crs_io.haversine_km(0.0, 0.0, 1.0, 0.0) == pytest.approx(6371.0088 * np.pi / 180.0)
    assert crs_io.haversine_km(2.0, 48.0, 2.0, 48.0) == 0.0
