"""A copy derived from a DEM or lake file of the user is no file of the user and no row.

The DEM converted from an ASC file, the lake-abacus Parquet pivot, the
lake-bathymetry COG and the lake-geometry GeoParquet live under
``data/blobs/<var>/file/`` with a name keyed on their inputs. That folder is a
place the scan of the data cache never enters, so a copy has no sidecar and
is no row, and the folder of the variable keeps only what a download wrote.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from hydromodpy.data.provenance.derived import derived_dir, derived_path
from hydromodpy.data.provenance.sidecars import CacheIndex, scan, sidecar_path_for
from hydromodpy.data.variables.dem.config import DemConfig, FileDemSource
from hydromodpy.data.variables.dem.custom import load_custom_dem
from hydromodpy.data.variables.dem.variable import DemVariable
from hydromodpy.data.variables.lake_abacus.config import (
    FileLakeAbacusSource,
    LakeAbacusConfig,
)
from hydromodpy.data.variables.lake_abacus.custom import load_custom_abacus
from hydromodpy.data.variables.lake_abacus.variable import LakeAbacusVariable
from hydromodpy.data.variables.lake_bathymetry.config import LakeBathymetryConfig
from hydromodpy.data.variables.lake_bathymetry.variable import LakeBathymetryVariable
from hydromodpy.data.variables.lake_geometry.config import LakeGeometryConfig
from hydromodpy.data.variables.lake_geometry.custom import load_custom_lake_geometry
from hydromodpy.data.variables.lake_geometry.variable import LakeGeometryVariable


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
        variable_class: Callable[..., Any],
        config: Callable[[Path], Any],
        kind: str,
        suffix: str,
        records: str,
    ) -> None:
        self.variable = variable
        self.file_name = file_name
        self.write = write
        self.variable_class = variable_class
        self.config = config
        self.kind = kind
        self.suffix = suffix
        self.records = records


_CASES = [
    _Case(
        "dem",
        "dem_custom_valley.asc",
        _write_asc,
        DemVariable,
        lambda p: DemConfig(sources=[FileDemSource(path=p)]),
        "geotiff",
        ".tif",
        "fields",
    ),
    _Case(
        "lake_abacus",
        "lake_abacus_custom_lac0.csv",
        _write_abacus,
        LakeAbacusVariable,
        lambda p: LakeAbacusConfig.from_csv(p, lake_id="lac0"),
        "pivot",
        ".parquet",
        "tables",
    ),
    _Case(
        "lake_bathymetry",
        "lake_bathymetry_custom_lac0.asc",
        _write_asc,
        LakeBathymetryVariable,
        LakeBathymetryConfig.from_raster,
        "cog",
        ".tif",
        "fields",
    ),
    _Case(
        "lake_geometry",
        "lake_geometry_custom_lac0.gpkg",
        _write_lake_polygon,
        LakeGeometryVariable,
        LakeGeometryConfig.from_vector,
        "geoparquet",
        ".parquet",
        "fields",
    ),
]


@pytest.mark.parametrize("case", _CASES, ids=[c.variable for c in _CASES])
def test_the_variable_writes_the_copy_under_blobs_and_it_is_no_row(
    tmp_path: Path, case: _Case
) -> None:
    data_root = tmp_path / "ws" / "data"
    var_dir = data_root / case.variable
    user_file = case.write(var_dir / case.file_name)
    before = sorted(p.name for p in var_dir.iterdir())

    index = CacheIndex(data_root)
    variable = case.variable_class(config=case.config(user_file), index=index, data_dir=var_dir)
    record = getattr(variable.load(), case.records)[0]
    copy = Path(record.data)

    assert copy.parent == data_root / "blobs" / case.variable / "file"
    assert copy.name.startswith(f"{user_file.stem}_{case.kind}_")
    assert copy.suffix == case.suffix
    assert sorted(p.name for p in var_dir.iterdir()) == before
    # Neither the user's file nor its copy is a row of the data cache.
    assert not sidecar_path_for(copy).exists()
    assert index.rows() == []
    assert scan(data_root).rows == ()

    copy.unlink()

    assert not copy.exists()
    assert user_file.is_file()


def test_two_dem_files_with_one_stem_give_two_copies(tmp_path: Path) -> None:
    first = _write_asc(tmp_path / "a" / "valley.asc", 80.0)
    second = _write_asc(tmp_path / "b" / "valley.asc", 90.0)
    derived = tmp_path / "derived"

    paths = [
        load_custom_dem(FileDemSource(path=p), derived_dir=derived)[0].data for p in (first, second)
    ]

    assert paths[0] != paths[1]
    assert all(Path(p).is_file() for p in paths)


def test_two_lake_ids_give_two_abacus_pivots(tmp_path: Path) -> None:
    source = _write_abacus(tmp_path / "abacus.csv")
    derived = tmp_path / "derived"

    records = [
        load_custom_abacus(FileLakeAbacusSource(path=source, lake_id=lake), derived_dir=derived)[0]
        for lake in ("lac0", "lac1")
    ]

    assert records[0].data != records[1].data
    assert [r.frame["lake_id"].unique().tolist() for r in records] == [["lac0"], ["lac1"]]


def test_two_lake_files_with_one_stem_give_two_copies(tmp_path: Path) -> None:
    derived = tmp_path / "derived"
    rasters = [_write_asc(tmp_path / d / "lac0.asc") for d in ("a", "b")]
    vectors = [_write_lake_polygon(tmp_path / d / "lac0.gpkg") for d in ("a", "b")]

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

    assert derived_dir(data_root / "dem", "dem") == data_root / "blobs" / "dem" / "file"
    assert derived_dir(None, "dem") is None
