"""``terrain-delineate`` records the box its DEM covers, not a bare CRS.

The DEM resource of ``inputset.json`` used to carry ``{"crs": ...}`` alone,
which names no place. It now carries the raster bounds in ``crs_project``,
the one extent shape a view reads.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from hydromodpy.core.exceptions import DataContractViolation
from hydromodpy.schema.job.extent import SpatialExtent
from hydromodpy.spatial.site_selection.hydrology.capability import TerrainDelineateRequest
from hydromodpy.spatial.site_selection.hydrology.worker import _build_inputset, _dem_extent

rasterio = pytest.importorskip("rasterio")

pytestmark = pytest.mark.fast

CELL = 25.0
WEST = 385000.0
NORTH = 6827300.0


def _dem(path: Path, *, south_up: bool = False, degenerate: bool = False) -> Path:
    from rasterio.transform import Affine

    rows, cols = 4, 6
    if degenerate:
        transform = Affine(0.0, 0.0, WEST, 0.0, 0.0, NORTH)
    elif south_up:
        transform = Affine(CELL, 0.0, WEST, 0.0, CELL, NORTH - rows * CELL)
    else:
        transform = Affine(CELL, 0.0, WEST, 0.0, -CELL, NORTH)
    with rasterio.open(
        str(path),
        "w",
        driver="GTiff",
        height=rows,
        width=cols,
        count=1,
        dtype="float32",
        crs="EPSG:2154",
        transform=transform,
    ) as dst:
        dst.write(np.ones((1, rows, cols), dtype="float32"))
    return path


def _request(dem: Path) -> TerrainDelineateRequest:
    return TerrainDelineateRequest.model_validate(
        {
            "dem": {"href": str(dem)},
            "outlets": [{"site_id": "valley", "x": WEST + 50.0, "y": NORTH - 50.0}],
            "crs_project": "EPSG:2154",
        }
    )


EXPECTED = (WEST, NORTH - 4 * CELL, WEST + 6 * CELL, NORTH)


def test_the_dem_extent_is_its_bounds_in_the_project_crs(tmp_path: Path) -> None:
    dem = _dem(tmp_path / "dem.tif")

    extent = _dem_extent(_request(dem), path=dem)

    assert extent == SpatialExtent(bbox=EXPECTED, crs="EPSG:2154")


def test_a_south_up_dem_gives_the_same_ordered_box(tmp_path: Path) -> None:
    dem = _dem(tmp_path / "dem.tif", south_up=True)

    assert _dem_extent(_request(dem), path=dem).bbox == EXPECTED


def test_a_dem_that_is_not_a_raster_is_still_refused(tmp_path: Path) -> None:
    dem = tmp_path / "dem.tif"
    dem.write_text("this is prose", encoding="utf-8")

    with pytest.raises(DataContractViolation, match="cannot be opened as a raster"):
        _dem_extent(_request(dem), path=dem)


def test_a_dem_whose_transform_covers_no_area_is_refused_as_bad_input(tmp_path: Path) -> None:
    dem = _dem(tmp_path / "dem.tif", degenerate=True)

    with pytest.raises(DataContractViolation, match="gives no valid extent"):
        _dem_extent(_request(dem), path=dem)


def test_the_input_set_carries_the_dem_box_and_its_crs(tmp_path: Path) -> None:
    dem = _dem(tmp_path / "dem.tif")
    inputs = _request(dem)
    effective = inputs.model_dump(mode="json")

    inputset = _build_inputset(
        dem_digest="a" * 64,
        dem_bytes=4,
        dem_extent=_dem_extent(inputs, path=dem),
        inputs=inputs,
        effective_inputs=effective,
    )

    resource = next(one for one in inputset.to_document()["resources"] if one["name"] == "dem")
    assert resource["spatial"] == {"crs": "EPSG:2154", "bbox": list(EXPECTED)}
