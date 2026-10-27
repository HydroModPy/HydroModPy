"""The mesh inputs carry the outlet the configuration declares.

The planner keeps a river end on the smoothed catchment outline. With
``[mesh.families] rivers = "none"`` no river end exists, so the outlet itself
has to reach the planner: the mesh step reads it from ``[geographic]``, the
place the lake structures read it from too.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np

from hydromodpy.spatial.geographic.geographic_config import GeographicConfig
from hydromodpy.spatial.mesh.mesh_config import MeshConfig
from hydromodpy.spatial.raster_support import RasterSupport
from hydromodpy.spatial.surface import Surface
from hydromodpy.workflow.steps.mesh_inputs import planning_inputs

_MESH = MeshConfig(engine="triangle", families={"rivers": "none", "geology": "none"})


def _ctx(geographic: GeographicConfig, cells: int = 10) -> SimpleNamespace:
    """The slice of a run context the mesh inputs read, over a square DEM."""
    support = RasterSupport(
        crs="EPSG:2154",
        dx=10.0,
        dy=10.0,
        xmin=0.0,
        xmax=10.0 * cells,
        ymin=0.0,
        ymax=10.0 * cells,
        nrows=cells,
        ncols=cells,
        nodata=-9999.0,
    )
    surface = Surface.from_geographic_dem(np.zeros((cells, cells)), support=support)
    return SimpleNamespace(
        cfg=SimpleNamespace(geographic=geographic, flow=SimpleNamespace(active_bc=[])),
        config_path=Path("project.toml"),
        setup=SimpleNamespace(
            domain=SimpleNamespace(surface_topo=surface),
            geographic=SimpleNamespace(crs_project="EPSG:2154"),
            domain_geographic=None,
            geographic_features=None,
            flow=None,
            workspace=None,
        ),
    )


def test_the_declared_outlet_reaches_the_planning_inputs() -> None:
    geographic = GeographicConfig.from_outlet(x=389285.91, y=6816518.749, dem="dem.tif")

    outlet = planning_inputs(_ctx(geographic), _MESH).outlet

    assert (outlet.x, outlet.y) == (389285.91, 6816518.749)


def test_a_catchment_without_a_declared_outlet_has_none() -> None:
    geographic = GeographicConfig.from_dem("dem.tif")

    assert planning_inputs(_ctx(geographic), _MESH).outlet is None
