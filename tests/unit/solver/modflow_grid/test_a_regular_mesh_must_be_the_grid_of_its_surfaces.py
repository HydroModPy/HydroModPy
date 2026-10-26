"""A regular mesh is extruded on the surfaces only if both describe one grid.

The planar grid is the mesh's, the vertical part is the surfaces'. A mesh shifted
by a metre, a step off by a part in a million, or a mesh that forgets its shape
would move every cell against its elevation without a single array mismatch, so
the builder refuses them.
"""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from hydromodpy.core.exceptions import MeshError
from hydromodpy.solver.modflow_grid import build_spatial_discretization
from hydromodpy.spatial import RasterSupport, Surface
from hydromodpy.spatial.domain import Domain, DomainConfig
from hydromodpy.spatial.mesh.cartesian_grid.sgrid_config import (
    SolverSGridConfig,
    VerticalGridConfig,
)
from hydromodpy.spatial.mesh.model.planar_cell_mesh import PlanarCellMesh
from tests._helpers.regular_cell_meshes import regular_cell_mesh

_N = 6
_STEP = 40.0
_XMIN = 1_000.0
_YMIN = 2_000.0


def _surface(name: str, value: float) -> Surface:
    support = RasterSupport(
        crs="EPSG:2154",
        dx=_STEP,
        dy=_STEP,
        xmin=_XMIN,
        xmax=_XMIN + _STEP * _N,
        ymin=_YMIN,
        ymax=_YMIN + _STEP * _N,
        nrows=_N,
        ncols=_N,
        nodata=-9999.0,
    )
    return Surface(name=name, values=np.full((_N, _N), value), support=support)


def _domain() -> Domain:
    domain = Domain(config=DomainConfig(), surface_topo=_surface("surface_topo", 20.0))
    domain.substratum = _surface("substratum", 0.0)
    return domain


def _extrude(cell_mesh: PlanarCellMesh):
    return build_spatial_discretization(
        domain=_domain(),
        vertical_config=VerticalGridConfig(nlay=1, nodata=-9999.0),
        sgrid_config=SolverSGridConfig(),
        cell_mesh=cell_mesh,
    )


def _mesh(**changes: float) -> PlanarCellMesh:
    arguments = {"xmin": _XMIN, "ymin": _YMIN, "dx": _STEP, "dy": _STEP, "nrow": _N, "ncol": _N}
    return regular_cell_mesh(**{**arguments, **changes})


def test_a_mesh_on_the_grid_of_the_surfaces_is_extruded() -> None:
    ctx = _extrude(_mesh())

    assert ctx.solver_mesh.structured_shape == (_N, _N)


@pytest.mark.parametrize(
    "changes",
    [
        {"xmin": _XMIN + 1.0},
        {"ymin": _YMIN - 1.0},
        {"dx": _STEP * (1.0 + 1e-6)},
        {"dy": _STEP * (1.0 - 1e-6)},
    ],
    ids=["shifted_east", "shifted_south", "wider_cells", "shorter_cells"],
)
def test_a_mesh_off_the_grid_of_the_surfaces_is_refused(changes: dict[str, float]) -> None:
    with pytest.raises(MeshError, match="differ"):
        _extrude(_mesh(**changes))


def test_a_mesh_that_forgets_its_shape_on_the_hydro_mesh_is_refused() -> None:
    cell_mesh = _mesh()
    forgetful = replace(cell_mesh, mesh=replace(cell_mesh.mesh, structured_shape=None))

    with pytest.raises(MeshError, match="shape"):
        _extrude(forgetful)


def test_a_mesh_of_another_shape_resamples_the_surfaces_on_its_own_grid() -> None:
    ctx = _extrude(_mesh(dx=_STEP * 2, dy=_STEP * 3, nrow=_N // 3, ncol=_N // 2))

    assert ctx.solver_mesh.structured_shape == (_N // 3, _N // 2)
    assert ctx.top_surface.as_array().shape == (_N // 3, _N // 2)
    assert np.allclose(ctx.solver_mesh.top, 20.0)
