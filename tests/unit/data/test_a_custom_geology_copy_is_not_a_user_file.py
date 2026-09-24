"""A copy derived from a custom geology file never lands among the user's files.

The clipped copy of ``GEO1M.shp`` was written as
``data/geology/geology_custom_GEO1M.gpkg``: the name of a user drop-in file,
shared by every project whatever its bbox. It now lives under
``data/blobs/geology/custom/`` with a name keyed on the source and the bbox,
and its sidecar sits beside it.
"""

from __future__ import annotations

from pathlib import Path

from hydromodpy.data.provenance.sidecars import load_sidecar, sidecar_path_for
from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB
from hydromodpy.data.variables.geology.config import CustomGeologySource, GeologyConfig
from hydromodpy.data.variables.geology.custom import load_custom_geology
from hydromodpy.data.variables.geology.manager import GeologyManager


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


def _source(path: Path, **kwargs) -> CustomGeologySource:
    return CustomGeologySource(source="custom", path=path, code_field="CODE", **kwargs)


def test_the_manager_writes_the_clip_under_blobs_with_its_sidecar(tmp_path: Path) -> None:
    data_root = tmp_path / "ws" / "data"
    geology_dir = data_root / "geology"
    user_file = _write_polygons(geology_dir / "GEO1M.gpkg")
    mask = _write_mask(tmp_path / "mask.gpkg", (10, 10, 40, 40))
    before = sorted(p.name for p in geology_dir.iterdir())

    catalog = DataCatalogDuckDB(data_root / "cache.duckdb")
    try:
        manager = GeologyManager(
            config=GeologyConfig(sources=[_source(user_file, mask_path=mask)]),
            catalog=catalog,
            data_dir=geology_dir,
        )
        record = manager.load().fields[0]
    finally:
        catalog.close()

    clip = Path(record.data)
    assert clip.parent == data_root / "blobs" / "geology" / "custom"
    assert clip.name.startswith("GEO1M_clip_")
    assert sorted(p.name for p in geology_dir.iterdir()) == before
    assert load_sidecar(clip).source == "custom"
    assert sidecar_path_for(clip).parent == clip.parent


def test_two_bboxes_give_two_copies(tmp_path: Path) -> None:
    user_file = _write_polygons(tmp_path / "GEO1M.gpkg")
    derived = tmp_path / "derived"

    first = load_custom_geology(
        _source(user_file), code_field="CODE", bbox=(0, 0, 40, 40), derived_dir=derived
    )[0]
    second = load_custom_geology(
        _source(user_file), code_field="CODE", bbox=(60, 60, 100, 100), derived_dir=derived
    )[0]

    assert first.data != second.data
    assert Path(first.data).is_file()
    assert Path(second.data).is_file()


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
