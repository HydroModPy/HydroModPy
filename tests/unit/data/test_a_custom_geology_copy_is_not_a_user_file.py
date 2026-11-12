"""A copy derived from a geology file of the user is no file of the user and no row.

The clipped copy of ``GEO1M.shp`` lives under ``data/blobs/geology/file/`` with a
name keyed on the source and the bbox. The scan of the data cache never enters
that folder, so the copy has no sidecar and the folder of the variable keeps only
what a download wrote.
"""

from __future__ import annotations

from pathlib import Path

from hydromodpy.data.provenance.sidecars import CacheIndex, sidecar_path_for
from hydromodpy.data.variables.geology.config import FileGeologySource, GeologyConfig
from hydromodpy.data.variables.geology.custom import load_custom_geology
from hydromodpy.data.variables.geology.variable import GeologyVariable


def _write_polygons(path: Path) -> Path:
    import geopandas as gpd
    from shapely.geometry import box

    gdf = gpd.GeoDataFrame(
        {"CODE": ["A", "B"]},
        geometry=[box(0, 0, 50, 100), box(50, 0, 100, 100)],
        crs="EPSG:2154",
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    gdf.to_file(str(path), driver="GPKG")
    return path


def _write_mask(path: Path, bounds: tuple[float, float, float, float]) -> Path:
    import geopandas as gpd
    from shapely.geometry import box

    gpd.GeoDataFrame(geometry=[box(*bounds)], crs="EPSG:2154").to_file(str(path), driver="GPKG")
    return path


def _source(path: Path, **kwargs) -> FileGeologySource:
    return FileGeologySource(source="file", path=path, code_field="CODE", **kwargs)


def test_the_variable_writes_the_clip_under_blobs_and_it_is_no_row(tmp_path: Path) -> None:
    data_root = tmp_path / "ws" / "data"
    geology_dir = data_root / "geology"
    user_file = _write_polygons(geology_dir / "GEO1M.gpkg")
    mask = _write_mask(tmp_path / "mask.gpkg", (10, 10, 40, 40))
    before = sorted(p.name for p in geology_dir.iterdir())

    index = CacheIndex(data_root)
    variable = GeologyVariable(
        config=GeologyConfig(sources=[_source(user_file, mask_path=mask)]),
        index=index,
        data_dir=geology_dir,
    )
    record = variable.load().fields[0]

    clip = Path(record.data)
    assert clip.parent == data_root / "blobs" / "geology" / "file"
    assert clip.name.startswith("GEO1M_clip_")
    assert sorted(p.name for p in geology_dir.iterdir()) == before
    assert not sidecar_path_for(clip).exists()
    assert index.rows() == []


def test_the_same_bbox_gives_the_same_copy(tmp_path: Path) -> None:
    user_file = _write_polygons(tmp_path / "GEO1M.gpkg")
    derived = tmp_path / "derived"

    runs = [
        load_custom_geology(
            _source(user_file), code_field="CODE", bbox=(0, 0, 40, 40), derived_dir=derived
        )[0].data
        for _ in range(2)
    ]

    assert runs[0] == runs[1]
    assert [p.name for p in derived.iterdir()] == [Path(runs[0]).name]


def test_a_voronoi_copy_goes_to_the_derived_directory(tmp_path: Path) -> None:
    points = tmp_path / "points.csv"
    points.write_text("x,y,geology_code\n10,10,A\n90,90,B\n10,90,C\n", encoding="utf-8")
    derived = tmp_path / "derived"

    record = load_custom_geology(_source(points), bbox=(0, 0, 100, 100), derived_dir=derived)[0]

    assert Path(record.data).parent == derived
    assert Path(record.data).name.startswith("points_voronoi_")
    assert [p.name for p in tmp_path.iterdir() if p.is_file()] == ["points.csv"]
