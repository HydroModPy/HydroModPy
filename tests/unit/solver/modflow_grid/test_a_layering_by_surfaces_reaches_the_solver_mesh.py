"""A layering by surfaces goes from the domain rasters to the solver mesh.

The domain places each layer base raster on the grid of its top. The
discretization samples it on the cells, a regular grid as a mesh of triangles,
and the weathered layer that thins out across the plan pinches into
pass-through cells whose thickness the layer below takes.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.core.exceptions import ConfigError, DataContractViolation
from hydromodpy.solver.modflow_grid import build_spatial_discretization
from hydromodpy.solver.modflow_nwt.nwt.nwt_solver import ModflowNwt
from hydromodpy.spatial import RasterSupport, Surface
from hydromodpy.spatial.domain import Domain, DomainConfig
from hydromodpy.spatial.mesh import registry
from hydromodpy.spatial.mesh.model.cell_types import CellType
from hydromodpy.spatial.mesh.model.hydro_mesh import CellBlock, HydroMesh
from hydromodpy.spatial.mesh.request import RasterGridSpec
from tests._helpers.cell_meshes import TEST_CRS_WKT, cell_mesh_of
from tests._helpers.mesh_cases import mesh_request

NODATA = -9999.0
STEP = 100.0
NROW, NCOL = 4, 6
WEATHERED_M = np.linspace(8.0, 0.0, NCOL)
"""Thickness of the weathered layer, column by column: it vanishes to the east."""


def _support() -> RasterSupport:
    return RasterSupport(
        crs="EPSG:2154",
        dx=STEP,
        dy=STEP,
        xmin=0.0,
        xmax=STEP * NCOL,
        ymin=0.0,
        ymax=STEP * NROW,
        nrows=NROW,
        ncols=NCOL,
        nodata=NODATA,
    )


def _layers() -> dict:
    return {
        "genmtd_lay": "surfaces",
        "layer": [
            {"name": "weathered", "surface": "weathered_base", "min_thickness": 1.0},
            {"name": "fissured", "thickness": 20.0},
            {"name": "rock"},
        ],
    }


def _domain(base: np.ndarray | None = None) -> Domain:
    top = np.full((NROW, NCOL), 100.0)
    weathered_base = top - WEATHERED_M[None, :] if base is None else base
    return Domain(
        config=DomainConfig.model_validate(
            {"depth_model": {"kind": "constant_thickness", "thickness": 60.0}, "layers": _layers()}
        ),
        surface_topo=Surface(name="surface_topo", values=top, support=_support()),
        layer_base_sources={
            "weathered_base": Surface(name="w", values=weathered_base, support=_support())
        },
    )


def _regular_cell_mesh(domain: Domain):
    support = domain.surface_topo.support
    request = mesh_request(RasterGridSpec.from_raster_support(support, crs_wkt=TEST_CRS_WKT))
    return registry.create("regular").build(request)


def _triangle_cell_mesh():
    xs = np.linspace(50.0, STEP * NCOL - 50.0, NCOL)
    ys = np.linspace(50.0, STEP * NROW - 50.0, NROW)
    node_x, node_y = (a.reshape(-1) for a in np.meshgrid(xs, ys))
    triangles = []
    for j in range(NROW - 1):
        for i in range(NCOL - 1):
            a, b = j * NCOL + i, j * NCOL + i + 1
            c, d = (j + 1) * NCOL + i + 1, (j + 1) * NCOL + i
            triangles.extend([(a, b, c), (a, c, d)])
    mesh = HydroMesh(
        vertices=np.column_stack([node_x, node_y]),
        cell_blocks=(CellBlock(CellType.TRIANGLE, np.asarray(triangles, dtype=int)),),
    )
    return cell_mesh_of(mesh)


def test_the_domain_places_each_layer_base_on_its_top_grid() -> None:
    domain = _domain()

    assert list(domain.layer_bases) == ["weathered_base"]
    np.testing.assert_allclose(
        domain.layer_bases["weathered_base"].as_array()[0], 100.0 - WEATHERED_M
    )


def test_the_domain_refuses_a_base_it_reads_and_was_not_given() -> None:
    with pytest.raises(ConfigError, match="none was given to the domain"):
        Domain(
            config=DomainConfig.model_validate({"layers": _layers()}),
            surface_topo=Surface(
                name="surface_topo", values=np.full((NROW, NCOL), 100.0), support=_support()
            ),
        )


def test_the_domain_refuses_a_base_raster_that_leaves_a_cell_without_value() -> None:
    base = np.full((NROW, NCOL), 95.0)
    base[1, 2] = np.nan

    with pytest.raises(DataContractViolation, match="leaves 1 of the 24 cells"):
        _domain(base)


def test_a_regular_grid_pinches_the_weathered_layer_where_it_thins_out() -> None:
    domain = _domain()

    mesh = build_spatial_discretization(
        domain=domain,
        vertical_config=domain.config.layers,
        sgrid_config=None,
        cell_mesh=_regular_cell_mesh(domain),
    ).solver_mesh

    idomain = mesh.idomain.reshape(3, NROW, NCOL)
    thin = WEATHERED_M < 1.0
    assert (idomain[0][:, thin] == -1).all()
    assert (idomain[0][:, ~thin] == 1).all()
    assert (idomain[1:] == 1).all()
    botm = mesh.botm.reshape(3, NROW, NCOL)
    np.testing.assert_allclose(botm[0][0], np.where(thin, 100.0, 100.0 - WEATHERED_M))
    np.testing.assert_allclose(botm[1][0], 100.0 - WEATHERED_M - 20.0)
    np.testing.assert_allclose(botm[2], 40.0)


def test_a_triangle_mesh_samples_the_base_at_its_cell_centres() -> None:
    domain = _domain()
    cell_mesh = _triangle_cell_mesh()

    mesh = build_spatial_discretization(
        domain=domain,
        vertical_config=domain.config.layers,
        sgrid_config=None,
        cell_mesh=cell_mesh,
    ).solver_mesh

    x_centres = cell_mesh.centers[:, 0]
    weathered = np.interp(x_centres, 50.0 + STEP * np.arange(NCOL), WEATHERED_M)
    thin = weathered < 1.0
    assert thin.any() and (~thin).any()
    np.testing.assert_array_equal(mesh.idomain[0], np.where(thin, -1, 1))
    np.testing.assert_allclose(mesh.layer_thicknesses()[0][~thin], weathered[~thin], atol=1e-6)
    np.testing.assert_allclose(mesh.layer_thicknesses()[1][thin], 20.0 + weathered[thin], atol=1e-6)


def test_modflow_nwt_refuses_a_grid_with_pass_through_cells() -> None:
    domain = _domain()
    solver = SimpleNamespace(cell_mesh=_regular_cell_mesh(domain), domain=domain, sgrid_config=None)

    with pytest.raises(ConfigError, match="MODFLOW-NWT does not have"):
        ModflowNwt._build_spatial_discretization(solver)
