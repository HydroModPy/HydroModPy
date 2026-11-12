"""Clipped copy of a geology file of the user, kept under ``data/blobs/geology``.

The copy of ``GEO1M`` is clipped to the request box (m, in the CRS of the mask)
and keyed on the source and the box. A file in another CRS is clipped after the
box is reprojected into the CRS of the file. A points file becomes a Voronoi copy.
"""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import pytest
from shapely.geometry import box

from hydromodpy.data.provenance.sidecars import CacheIndex, sidecar_path_for
from hydromodpy.data.variables.geology.config import FileGeologySource, GeologyConfig
from hydromodpy.data.variables.geology.custom import load_custom_geology
from hydromodpy.data.variables.geology.variable import GeologyVariable

# Two units side by side near Rennes, drawn in Lambert-93.
UNITS_L93 = [
    box(350_000, 6_780_000, 352_000, 6_784_000),
    box(352_000, 6_780_000, 354_000, 6_784_000),
]
MASK_L93 = (351_000, 6_781_000, 353_000, 6_783_000)


def write_polygons(path: Path) -> Path:
    # Two units of 50 m x 100 m, side by side.
    gdf = gpd.GeoDataFrame(
        {"CODE": ["A", "B"]},
        geometry=[box(0, 0, 50, 100), box(50, 0, 100, 100)],
        crs="EPSG:2154",
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    gdf.to_file(str(path), driver="GPKG")
    return path


def write_units_in_wgs84(path: Path) -> Path:
    frame = gpd.GeoDataFrame({"CODE": ["A", "B"]}, geometry=UNITS_L93, crs="EPSG:2154")
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_crs("EPSG:4326").to_file(str(path), driver="GPKG")
    return path


def write_mask(path: Path, bounds: tuple[float, float, float, float], crs="EPSG:2154") -> Path:
    gpd.GeoDataFrame(geometry=[box(*bounds)], crs=crs).to_file(str(path), driver="GPKG")
    return path


def file_source(path: Path, **kwargs) -> FileGeologySource:
    return FileGeologySource(source="file", path=path, code_field="CODE", **kwargs)


def geology_variable(
    data_root: Path, source: FileGeologySource, index: CacheIndex | None = None
) -> GeologyVariable:
    return GeologyVariable(
        config=GeologyConfig(sources=[source]),
        index=index or CacheIndex(data_root),
        data_dir=data_root / "geology",
    )


def test_clip_under_blobs_is_no_row(tmp_path):
    data_root = tmp_path / "ws" / "data"
    geology_dir = data_root / "geology"
    user_file = write_polygons(geology_dir / "GEO1M.gpkg")
    mask = write_mask(tmp_path / "mask.gpkg", (10, 10, 40, 40))
    before = sorted(p.name for p in geology_dir.iterdir())

    index = CacheIndex(data_root)
    variable = geology_variable(data_root, file_source(user_file, mask_path=mask), index)
    clip = Path(variable.load().fields[0].data)

    assert clip.parent == data_root / "blobs" / "geology" / "file"
    assert clip.name.startswith("GEO1M_clip_")
    assert sorted(p.name for p in geology_dir.iterdir()) == before
    assert not sidecar_path_for(clip).exists()
    assert index.rows() == []


def test_same_box_gives_the_same_copy(tmp_path):
    user_file = write_polygons(tmp_path / "GEO1M.gpkg")
    derived = tmp_path / "derived"

    runs = [
        load_custom_geology(
            file_source(user_file), code_field="CODE", bbox=(0, 0, 40, 40), derived_dir=derived
        )[0].data
        for _ in range(2)
    ]

    assert runs[0] == runs[1]
    assert [p.name for p in derived.iterdir()] == [Path(runs[0]).name]


def test_voronoi_copy_goes_to_the_derived_directory(tmp_path):
    points = tmp_path / "points.csv"
    points.write_text("x,y,geology_code\n10,10,A\n90,90,B\n10,90,C\n", encoding="utf-8")
    derived = tmp_path / "derived"

    record = load_custom_geology(file_source(points), bbox=(0, 0, 100, 100), derived_dir=derived)[0]

    assert Path(record.data).parent == derived
    assert Path(record.data).name.startswith("points_voronoi_")
    assert [p.name for p in tmp_path.iterdir() if p.is_file()] == ["points.csv"]


def test_wgs84_file_is_clipped_by_a_lambert_mask(tmp_path):
    data_root = tmp_path / "ws" / "data"
    user_file = write_units_in_wgs84(data_root / "geology" / "units.gpkg")
    mask = write_mask(tmp_path / "mask.gpkg", MASK_L93)

    variable = geology_variable(data_root, file_source(user_file, mask_path=mask))
    record = variable.load().fields[0]

    clipped = gpd.read_file(str(record.data))
    assert sorted(clipped["CODE"]) == ["A", "B"]
    assert str(record.crs).upper().endswith("4326")
    # The clip covers the mask and keeps little more: the box reprojected into
    # WGS84 is a slightly turned square, and the clip takes its envelope.
    held = clipped.to_crs("EPSG:2154").total_bounds
    assert held[0] <= MASK_L93[0] and held[1] <= MASK_L93[1]
    assert held[2] >= MASK_L93[2] and held[3] >= MASK_L93[3]
    assert held[0] > 350_000 and held[2] < 354_000


def test_box_missing_the_file_names_file_and_crs(tmp_path):
    user_file = write_units_in_wgs84(tmp_path / "units.gpkg")

    with pytest.raises(ValueError, match=r"No geology feature of units\.gpkg intersects"):
        load_custom_geology(
            file_source(user_file),
            code_field="CODE",
            bbox=(100_000, 6_100_000, 101_000, 6_101_000),
            bbox_crs="EPSG:2154",
            derived_dir=tmp_path / "derived",
        )
