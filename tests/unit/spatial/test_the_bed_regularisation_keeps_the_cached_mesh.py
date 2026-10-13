"""Toggling the bed regularisation keeps the cached mesh.

The bed regularisation writes the surface the model top is sampled from,
after the mesh inputs are built. The mesh request leaves it out, so a run
with the option on hits the mesh of a run with it off.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np

from hydromodpy.spatial.geographic.geographic_config import GeographicConfig
from hydromodpy.spatial.mesh.cache import cache_key
from hydromodpy.spatial.mesh.config.mesh import MeshConfig
from hydromodpy.spatial.mesh.engines.triangle.engine import TriangleMeshEngine
from hydromodpy.spatial.mesh.planning import plan_mesh_request
from hydromodpy.spatial.raster_support import RasterSupport
from hydromodpy.spatial.surface import Surface
from hydromodpy.workflow.steps.mesh_inputs import planning_inputs

_RIVER = {"enabled": True, "threshold_mode": "cells", "threshold_cells": 50}


def _geographic(**bed) -> GeographicConfig:
    return GeographicConfig.from_outlet(
        x=1.0, y=2.0, dem="dem.tif", river_network=_RIVER, bed_regularization=bed
    )


def _ctx(geographic: GeographicConfig, *, cells: int = 10) -> SimpleNamespace:
    """The slice of a run context the planner reads, over a square DEM of ``cells`` pixels."""
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


def _key(ctx: SimpleNamespace) -> str:
    mesh_cfg = MeshConfig(engine="triangle", families={"rivers": "none", "geology": "none"})
    request = plan_mesh_request(mesh_cfg, planning_inputs(ctx, mesh_cfg))
    return cache_key(request, TriangleMeshEngine)


def test_the_bed_regularisation_keeps_the_cached_mesh() -> None:
    off = _ctx(_geographic(enabled=False))
    on = _ctx(_geographic(enabled=True, min_slope=5.0e-4))

    assert _key(on) == _key(off)


def test_another_dem_still_moves_the_key() -> None:
    assert _key(_ctx(_geographic(enabled=False))) != _key(
        _ctx(_geographic(enabled=False), cells=12)
    )
