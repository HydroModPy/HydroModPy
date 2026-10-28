"""``terrain-delineate`` records the box its DEM covers, not a bare CRS.

The DEM resource of ``inputset.json`` used to carry ``{"crs": ...}`` alone,
which names no place. It now carries the raster bounds in ``crs_project``,
the one extent shape a view reads.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from hydromodpy.cli.helpers import exit_code_for
from hydromodpy.core.exceptions import DataContractViolation
from hydromodpy.schema.job import JobDirectory, read_document
from hydromodpy.schema.job.extent import SpatialExtent
from hydromodpy.spatial.site_selection.hydrology import worker
from hydromodpy.spatial.site_selection.hydrology.capability import TerrainDelineateRequest
from hydromodpy.spatial.site_selection.hydrology.worker import _build_inputset, _dem_extent
from tests._helpers.geotiffs import write_geotiff

rasterio = pytest.importorskip("rasterio")

pytestmark = pytest.mark.fast

CELL = 25.0
WEST = 385000.0
NORTH = 6827300.0
EXPECTED = (WEST, NORTH - 4 * CELL, WEST + 6 * CELL, NORTH)
ONES = np.ones((4, 6), dtype="float32")


def _request(dem: Path) -> TerrainDelineateRequest:
    return TerrainDelineateRequest.model_validate(
        {
            "dem": {"href": str(dem)},
            "outlets": [{"site_id": "valley", "x": WEST + 50.0, "y": NORTH - 50.0}],
            "crs_project": "EPSG:2154",
        }
    )


@pytest.mark.parametrize(
    ("origin", "cell"),
    [((WEST, NORTH), CELL), ((WEST, NORTH - 4 * CELL), (CELL, -CELL))],
    ids=["north_up", "south_up"],
)
def test_the_dem_extent_is_its_ordered_bounds_in_the_project_crs(tmp_path, origin, cell):
    dem = write_geotiff(tmp_path / "dem.tif", ONES, origin=origin, cell=cell)

    assert _dem_extent(_request(dem), path=dem) == SpatialExtent(bbox=EXPECTED, crs="EPSG:2154")


def test_a_dem_whose_grid_covers_no_area_is_refused_as_bad_input(tmp_path):
    path = write_geotiff(tmp_path / "dem.tif", ONES, origin=(WEST, NORTH), cell=0.0)

    with pytest.raises(DataContractViolation, match="gives no valid extent"):
        _dem_extent(_request(path), path=path)


def test_the_input_set_carries_the_dem_box_and_its_crs(tmp_path):
    dem = write_geotiff(tmp_path / "dem.tif", ONES, origin=(WEST, NORTH), cell=CELL)
    inputs = _request(dem)

    inputset = _build_inputset(
        dem_digest="a" * 64,
        dem_bytes=4,
        dem_extent=_dem_extent(inputs, path=dem),
        inputs=inputs,
        effective_inputs=inputs.model_dump(mode="json"),
    )

    resource = next(one for one in inputset.to_document()["resources"] if one["name"] == "dem")
    assert resource["spatial"] == {"crs": "EPSG:2154", "bbox": list(EXPECTED)}


def test_an_interrupted_job_is_dismissed_and_not_sealed(tmp_path, monkeypatch):
    dem = write_geotiff(tmp_path / "dem.tif", ONES, origin=(WEST, NORTH), cell=CELL)
    job = JobDirectory.create(tmp_path / "job")
    request = {"process": {"id": "terrain-delineate", "version": "1.1.0"}}
    request["inputs"] = _request(dem).model_dump(mode="json")
    job.request_path.write_text(json.dumps(request), encoding="utf-8")

    def interrupt(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(worker, "_produce", interrupt)

    with pytest.raises(KeyboardInterrupt):
        worker.run(job, exit_code_for=exit_code_for)

    assert read_document(job.outcome_path)["status"] == "dismissed"
    assert not job.is_sealed
