"""A copy derived from a custom DEM or lake file never lands among the user's files.

The DEM converted from an ASC file, the lake-abacus Parquet pivot, the
lake-bathymetry COG and the lake-geometry GeoParquet were written as
``data/<var>/<var>_custom_<stem>.<ext>``: the name of a user drop-in file,
which auto_scan ingests as user data, and one name per source stem whatever
produced it. They now live under ``data/blobs/<var>/custom/`` with a name
keyed on their inputs, and their sidecar lives and dies with them.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from hydromodpy.data.derived import custom_derived_dir, derived_path
from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB
from hydromodpy.data.sidecars import load_sidecar, sidecar_path_for, unlink_with_sidecar
from hydromodpy.data.variables.dem.config import CustomDemSource, DemConfig
from hydromodpy.data.variables.dem.custom import load_custom_dem
from hydromodpy.data.variables.dem.manager import DemManager
from hydromodpy.data.variables.lake_abacus.config import (
    CustomLakeAbacusSource,
    LakeAbacusConfig,
)
from hydromodpy.data.variables.lake_abacus.custom import load_custom_abacus
from hydromodpy.data.variables.lake_abacus.manager import LakeAbacusManager
from hydromodpy.data.variables.lake_bathymetry.config import LakeBathymetryConfig
from hydromodpy.data.variables.lake_bathymetry.custom import load_custom_lake_bathymetry
from hydromodpy.data.variables.lake_bathymetry.manager import LakeBathymetryManager
from hydromodpy.data.variables.lake_geometry.config import LakeGeometryConfig
from hydromodpy.data.variables.lake_geometry.custom import load_custom_lake_geometry
from hydromodpy.data.variables.lake_geometry.manager import LakeGeometryManager


def _write_asc(path: Path, value: float = 82.0) -> Path:
    import numpy as np
    import rasterio
    from rasterio.transform import from_origin

    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        str(path),
        "w",
        driver="AAIGrid",
        height=4,
        width=4,
        count=1,
        dtype="float32",
        crs="EPSG:2154",
        transform=from_origin(0.0, 100.0, 25.0, 25.0),
    ) as dst:
        dst.write(np.full((4, 4), value, dtype="float32"), 1)
    return path


def _write_abacus(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("stage,volume,sarea\n85.0,0.0,0.0\n90.0,1.0e6,4.0e5\n", encoding="utf-8")
    return path


def _write_lake_polygon(path: Path) -> Path:
    import geopandas as gpd
    from shapely.geometry import box

    path.parent.mkdir(parents=True, exist_ok=True)
    gpd.GeoDataFrame(
        {"name": ["lac0"]}, geometry=[box(0.0, 0.0, 100.0, 100.0)], crs="EPSG:2154"
    ).to_file(str(path), driver="GPKG")
    return path


class _Case:
    def __init__(
        self,
        variable: str,
        file_name: str,
        write: Callable[[Path], Path],
        manager: Callable[..., Any],
        config: Callable[[Path], Any],
        kind: str,
        suffix: str,
        records: str,
    ) -> None:
        self.variable = variable
        self.file_name = file_name
        self.write = write
        self.manager = manager
        self.config = config
        self.kind = kind
        self.suffix = suffix
        self.records = records


_CASES = [
    _Case(
        "dem",
        "dem_custom_valley.asc",
        _write_asc,
        DemManager,
        lambda p: DemConfig(sources=[CustomDemSource(path=p)]),
        "geotiff",
        ".tif",
        "fields",
    ),
    _Case(
        "lake_abacus",
        "lake_abacus_custom_lac0.csv",
        _write_abacus,
        LakeAbacusManager,
        lambda p: LakeAbacusConfig.from_csv(p, lake_id="lac0"),
        "pivot",
        ".parquet",
        "tables",
    ),
    _Case(
        "lake_bathymetry",
        "lake_bathymetry_custom_lac0.asc",
        _write_asc,
        LakeBathymetryManager,
        LakeBathymetryConfig.from_raster,
        "cog",
        ".tif",
        "fields",
    ),
    _Case(
        "lake_geometry",
        "lake_geometry_custom_lac0.gpkg",
        _write_lake_polygon,
        LakeGeometryManager,
        LakeGeometryConfig.from_vector,
        "geoparquet",
        ".parquet",
        "fields",
    ),
]


@pytest.mark.parametrize("case", _CASES, ids=[c.variable for c in _CASES])
def test_the_manager_writes_the_copy_under_blobs_and_the_sidecar_follows_it(
    tmp_path: Path, case: _Case
) -> None:
    data_root = tmp_path / "ws" / "data"
    var_dir = data_root / case.variable
    user_file = case.write(var_dir / case.file_name)
    before = sorted(p.name for p in var_dir.iterdir())

    catalog = DataCatalogDuckDB(data_root / "cache.duckdb")
    try:
        manager = case.manager(config=case.config(user_file), catalog=catalog, data_dir=var_dir)
        record = getattr(manager.load(), case.records)[0]
        copy = Path(record.data)

        assert copy.parent == data_root / "blobs" / case.variable / "custom"
        assert copy.name.startswith(f"{user_file.stem}_{case.kind}_")
        assert copy.suffix == case.suffix
        assert sorted(p.name for p in var_dir.iterdir()) == before
        assert load_sidecar(copy).source == "custom"
        assert sidecar_path_for(copy).parent == copy.parent
    finally:
        catalog.close()

    unlink_with_sidecar(copy)

    assert not copy.exists()
    assert not sidecar_path_for(copy).exists()
    assert user_file.is_file()


def test_two_dem_files_with_one_stem_give_two_copies(tmp_path: Path) -> None:
    first = _write_asc(tmp_path / "a" / "valley.asc", 80.0)
    second = _write_asc(tmp_path / "b" / "valley.asc", 90.0)
    derived = tmp_path / "derived"

    paths = [
        load_custom_dem(CustomDemSource(path=p), derived_dir=derived)[0].data
        for p in (first, second)
    ]

    assert paths[0] != paths[1]
    assert all(Path(p).is_file() for p in paths)


def test_two_lake_ids_give_two_abacus_pivots(tmp_path: Path) -> None:
    source = _write_abacus(tmp_path / "abacus.csv")
    derived = tmp_path / "derived"

    records = [
        load_custom_abacus(CustomLakeAbacusSource(path=source, lake_id=lake), derived_dir=derived)[
            0
        ]
        for lake in ("lac0", "lac1")
    ]

    assert records[0].data != records[1].data
    assert [r.frame["lake_id"].unique().tolist() for r in records] == [["lac0"], ["lac1"]]


def test_two_lake_files_with_one_stem_give_two_copies(tmp_path: Path) -> None:
    derived = tmp_path / "derived"
    rasters = [_write_asc(tmp_path / d / "lac0.asc") for d in ("a", "b")]
    vectors = [_write_lake_polygon(tmp_path / d / "lac0.gpkg") for d in ("a", "b")]

    bathy = [
        load_custom_lake_bathymetry(
            LakeBathymetryConfig.from_raster(p).sources[0], derived_dir=derived
        )[0].data
        for p in rasters
    ]
    geometry = [
        load_custom_lake_geometry(
            LakeGeometryConfig.from_vector(p).sources[0], derived_dir=derived
        )[0].data
        for p in vectors
    ]

    assert bathy[0] != bathy[1]
    assert geometry[0] != geometry[1]


def test_the_same_inputs_give_the_same_path(tmp_path: Path) -> None:
    source = tmp_path / "valley.asc"

    first = derived_path(tmp_path, source, kind="geotiff", suffix=".tif", inputs=("x",))
    again = derived_path(tmp_path, source, kind="geotiff", suffix=".tif", inputs=("x",))
    other = derived_path(tmp_path, source, kind="geotiff", suffix=".tif", inputs=("y",))

    assert first == again
    assert first != other
    assert first.name.startswith("valley_geotiff_")


def test_the_derived_dir_sits_under_blobs_beside_the_variable_folders(tmp_path: Path) -> None:
    data_root = tmp_path / "data"

    assert custom_derived_dir(data_root / "dem", "dem") == data_root / "blobs" / "dem" / "custom"
    assert custom_derived_dir(None, "dem") is None
