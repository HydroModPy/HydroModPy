"""Copies derived from a DEM or lake file of the user, kept under ``data/blobs``.

The DEM converted from an ASC file, the lake-abacus Parquet pivot, the
lake-bathymetry COG and the lake-geometry GeoParquet live under
``data/blobs/<var>/file/`` with a name keyed on their inputs. The data cache
scan never enters that folder, so a copy has no sidecar and is no row.
"""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import box

from hydromodpy.data.provenance.derived import derived_dir
from hydromodpy.data.provenance.sidecars import CacheIndex, scan, sidecar_path_for
from hydromodpy.data.variables.dem.config import DemConfig, FileDemSource
from hydromodpy.data.variables.dem.custom import load_custom_dem
from hydromodpy.data.variables.dem.variable import DemVariable
from hydromodpy.data.variables.lake_abacus.config import LakeAbacusConfig
from hydromodpy.data.variables.lake_abacus.variable import LakeAbacusVariable
from hydromodpy.data.variables.lake_bathymetry.config import LakeBathymetryConfig
from hydromodpy.data.variables.lake_bathymetry.variable import LakeBathymetryVariable
from hydromodpy.data.variables.lake_geometry.config import LakeGeometryConfig
from hydromodpy.data.variables.lake_geometry.custom import load_custom_lake_geometry
from hydromodpy.data.variables.lake_geometry.variable import LakeGeometryVariable


def write_asc(path: Path, value: float = 82.0) -> Path:
    # 4 x 4 cells of 25 m, Lambert-93.
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


def write_abacus(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("stage,volume,sarea\n85.0,0.0,0.0\n90.0,1.0e6,4.0e5\n", encoding="utf-8")
    return path


def write_lake_polygon(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    gpd.GeoDataFrame(
        {"name": ["lac0"]}, geometry=[box(0.0, 0.0, 100.0, 100.0)], crs="EPSG:2154"
    ).to_file(str(path), driver="GPKG")
    return path


# (variable, user file, writer, variable class, config of the file, copy kind, copy suffix, records)
COPIES = [
    pytest.param(
        "dem",
        "dem_custom_valley.asc",
        write_asc,
        DemVariable,
        lambda p: DemConfig(sources=[FileDemSource(path=p)]),
        "geotiff",
        ".tif",
        "fields",
        id="dem",
    ),
    pytest.param(
        "lake_abacus",
        "lake_abacus_custom_lac0.csv",
        write_abacus,
        LakeAbacusVariable,
        lambda p: LakeAbacusConfig.from_csv(p, lake_id="lac0"),
        "pivot",
        ".parquet",
        "tables",
        id="lake_abacus",
    ),
    pytest.param(
        "lake_bathymetry",
        "lake_bathymetry_custom_lac0.asc",
        write_asc,
        LakeBathymetryVariable,
        LakeBathymetryConfig.from_raster,
        "cog",
        ".tif",
        "fields",
        id="lake_bathymetry",
    ),
    pytest.param(
        "lake_geometry",
        "lake_geometry_custom_lac0.gpkg",
        write_lake_polygon,
        LakeGeometryVariable,
        LakeGeometryConfig.from_vector,
        "geoparquet",
        ".parquet",
        "fields",
        id="lake_geometry",
    ),
]


@pytest.mark.parametrize(
    ("variable", "file_name", "write", "variable_class", "config", "kind", "suffix", "records"),
    COPIES,
)
def test_copy_under_blobs_is_no_row(
    tmp_path, variable, file_name, write, variable_class, config, kind, suffix, records
):
    data_root = tmp_path / "ws" / "data"
    var_dir = data_root / variable
    user_file = write(var_dir / file_name)
    before = sorted(p.name for p in var_dir.iterdir())

    index = CacheIndex(data_root)
    loaded = variable_class(config=config(user_file), index=index, data_dir=var_dir)
    copy = Path(getattr(loaded.load(), records)[0].data)

    assert copy.parent == data_root / "blobs" / variable / "file"
    assert copy.name.startswith(f"{user_file.stem}_{kind}_")
    assert copy.suffix == suffix
    assert sorted(p.name for p in var_dir.iterdir()) == before
    # Neither the user's file nor its copy is a row of the data cache.
    assert not sidecar_path_for(copy).exists()
    assert index.rows() == []
    assert scan(data_root).rows == ()

    copy.unlink()

    assert user_file.is_file()


def test_two_dem_files_with_one_stem_give_two_copies(tmp_path):
    first = write_asc(tmp_path / "a" / "valley.asc", 80.0)
    second = write_asc(tmp_path / "b" / "valley.asc", 90.0)

    paths = [
        load_custom_dem(FileDemSource(path=p), derived_dir=tmp_path / "derived")[0].data
        for p in (first, second)
    ]

    assert paths[0] != paths[1]
    assert all(Path(p).is_file() for p in paths)


def test_two_lake_files_with_one_stem_give_two_copies(tmp_path):
    derived = tmp_path / "derived"
    rasters = [write_asc(tmp_path / d / "lac0.asc") for d in ("a", "b")]
    vectors = [write_lake_polygon(tmp_path / d / "lac0.gpkg") for d in ("a", "b")]

    bathy_variable = LakeBathymetryVariable(config=None, index=None)
    bathy = [
        bathy_variable.read_file_source(
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


def test_derived_dir(tmp_path):
    data_root = tmp_path / "data"

    assert derived_dir(data_root / "dem", "dem") == data_root / "blobs" / "dem" / "file"
    assert derived_dir(None, "dem") is None
