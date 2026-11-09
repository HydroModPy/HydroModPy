"""The planner inputs are plain frozen data on the DEM grid, in its CRS.

The mesh step reads the delineated catchment for an engine that grades its
cells, follows the catchment boundary or meshes the catchment as one cell.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import geopandas as gpd
import numpy as np
import pytest
from shapely import normalize
from shapely.geometry import LineString, box

from hydromodpy.catchment.preprocess.geographic_config import GeographicConfig
from hydromodpy.catchment.raster_support import RasterSupport
from hydromodpy.catchment.surface import Surface
from hydromodpy.mesh.mesh_config import MeshConfig
from hydromodpy.workflow.steps.mesh_inputs import planning_inputs as gather_planning_inputs
from tests._helpers.mesh_cases import LAMBERT93_WKT, grid_spec, planning_inputs


def test_the_inputs_are_in_the_crs_of_the_dem_grid() -> None:
    inputs = planning_inputs(grid_spec(4, 4, 10.0, crs_wkt=LAMBERT93_WKT))

    assert inputs.crs_wkt == inputs.dem_grid.crs_wkt == LAMBERT93_WKT


def test_the_sequences_of_the_inputs_are_kept_as_tuples() -> None:
    """A list handed by the mesh step cannot change after the request was hashed."""
    lake = box(100.0, 100.0, 200.0, 200.0)
    wall = LineString([(0.0, 0.0), (1.0, 1.0)])

    inputs = planning_inputs(lakes=[lake], barriers=[wall], notes=["a note"], refinement_zones=[])

    assert (inputs.lakes, inputs.barriers, inputs.notes) == ((lake,), (wall,), ("a note",))
    assert inputs.refinement_zones == () and inputs.lake_structures == ()


_CATCHMENT = box(10.0, 10.0, 90.0, 80.0)


def _ctx(tmp_path: Path) -> SimpleNamespace:
    """The slice of a run context the mesh step reads, over a 100 m DEM with a delineated catchment."""
    shp = tmp_path / "watershed.shp"
    gpd.GeoDataFrame(geometry=[_CATCHMENT], crs="EPSG:2154").to_file(shp)
    support = RasterSupport(
        crs="EPSG:2154",
        dx=10.0,
        dy=10.0,
        xmin=0.0,
        xmax=100.0,
        ymin=0.0,
        ymax=100.0,
        nrows=10,
        ncols=10,
        nodata=-9999.0,
    )
    return SimpleNamespace(
        cfg=SimpleNamespace(
            geographic=GeographicConfig.from_outlet(x=50.0, y=10.0),
            flow=SimpleNamespace(active_bc=[]),
        ),
        config_path=tmp_path / "project.toml",
        setup=SimpleNamespace(
            domain=SimpleNamespace(
                surface_topo=Surface.from_geographic_dem(np.zeros((10, 10)), support=support)
            ),
            geographic=SimpleNamespace(crs_project="EPSG:2154"),
            domain_geographic=SimpleNamespace(watershed_shp=shp),
            geographic_features=None,
            flow=None,
            workspace=None,
        ),
    )


@pytest.mark.parametrize(
    ("engine", "families", "reads"),
    [
        ("catchment", {}, True),
        ("voronoi", {}, True),
        ("regular", {"watershed_boundary": "face"}, True),
        ("regular", {}, False),
    ],
    ids=["lumped", "graded", "boundary_face", "regular_grid"],
)
def test_the_mesh_step_reads_the_catchment_when_the_engine_needs_it(
    tmp_path: Path, engine: str, families: dict[str, str], reads: bool
) -> None:
    mesh_cfg = MeshConfig(engine=engine, families={"rivers": "none", "geology": "none", **families})

    watershed = gather_planning_inputs(_ctx(tmp_path), mesh_cfg).watershed

    if reads:
        assert normalize(watershed).equals_exact(normalize(_CATCHMENT), 1.0e-6)
    else:
        assert watershed is None
