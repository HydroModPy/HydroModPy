from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.solver.modflow_grid import (
    build_spatial_discretization,
)
from hydromodpy.solver.modflow_nwt.nwt import ModflowNwt
from hydromodpy.spatial import RasterSupport, Surface
from hydromodpy.spatial.domain import Domain, DomainConfig
from hydromodpy.spatial.mesh import CellBlock, CellType, HydroMesh
from hydromodpy.spatial.mesh.cartesian_grid.sgrid_config import (
    SolverSGridConfig,
    VerticalGridConfig,
)
from tests._helpers.cell_meshes import cell_mesh_of
from tests._helpers.regular_cell_meshes import regular_cell_mesh_of_surface


class _DummyGeographic:
    def __init__(self, dem: np.ndarray):
        self.dem_res = 1.0
        self.xmin = 0.0
        self.ymax = float(dem.shape[0])
        self.dem_box_buff_data = np.asarray(dem, dtype=float)
        self.dem_data = np.asarray(dem, dtype=float)
        self.watershed_box_buff_dem = "dummy_box.tif"
        self.watershed_buff_dem = "dummy_buff.tif"


def _build_surface(
    values: np.ndarray,
    *,
    xmin: float = 0.0,
    ymin: float = 0.0,
    dx: float = 1.0,
    dy: float = 1.0,
    name: str = "surface",
) -> Surface:
    arr = np.asarray(values, dtype=float)
    nrows, ncols = arr.shape
    support = RasterSupport(
        crs="EPSG:2154",
        dx=dx,
        dy=dy,
        xmin=xmin,
        xmax=xmin + dx * ncols,
        ymin=ymin,
        ymax=ymin + dy * nrows,
        nrows=nrows,
        ncols=ncols,
        nodata=-9999.0,
    )
    return Surface(name=name, values=arr, support=support)


def _build_domain_from_dem(dem: np.ndarray) -> Domain:
    return Domain(
        config=DomainConfig(),
        surface_topo=_build_surface(np.asarray(dem, dtype=float), name="surface_topo"),
    )


def test_modflow_requires_domain_object_for_spatial_geometry():
    dem = np.array([[10.0, 11.0], [12.0, 13.0]], dtype=float)
    geo = _DummyGeographic(dem)

    model = ModflowNwt(
        geographic=geo,
        model_folder=".",
    )
    with pytest.raises(ValueError, match="domain-only: a Domain object is required"):
        model._get_domain_surfaces()


def test_modflow_domain_surfaces_are_required():
    dem = np.array([[10.0, 11.0], [12.0, 13.0]], dtype=float)
    geo = _DummyGeographic(dem)
    domain = _build_domain_from_dem(dem)

    domain.substratum = None
    model = ModflowNwt(geographic=geo, model_folder=".")
    model.domain = domain
    with pytest.raises(
        ValueError,
        match="domain.surface_topo and domain.substratum are required",
    ):
        model._get_domain_surfaces()


def test_modflow_validates_domain_support_match_on_surface_build():
    dem = np.array([[10.0, 11.0], [12.0, 13.0]], dtype=float)
    geo = _DummyGeographic(dem)
    domain = _build_domain_from_dem(dem)
    domain.substratum = _build_surface(
        np.array([[1.0, 2.0], [3.0, 4.0]], dtype=float),
        xmin=1.0,
        name="substratum",
    )

    model = ModflowNwt(
        geographic=geo,
        model_folder=".",
    )
    model.domain = domain

    with pytest.raises(ValueError, match="Domain extent mismatch"):
        model._get_domain_surfaces()


def test_build_spatial_discretization_resamples_to_solver_shape():
    top = np.array([[20.0, 22.0], [24.0, 26.0]], dtype=float)
    domain = _build_domain_from_dem(top)

    ctx = build_spatial_discretization(
        domain=domain,
        vertical_config=VerticalGridConfig(
            genmtd_lay="constant",
            nlay=2,
            nodata=-9999.0,
        ),
        sgrid_config=SolverSGridConfig(),
        cell_mesh=regular_cell_mesh_of_surface(domain.surface_topo, nrow=3, ncol=4),
    )

    assert ctx.nrow == 3
    assert ctx.ncol == 4
    assert ctx.top_elevation.shape == (12,)  # flat (n_cells,)
    assert ctx.bottom_layer.shape == (12,)
    assert ctx.solver_mesh.botm.shape == (2, 12)
    assert ctx.grid.dx == pytest.approx(0.5)
    assert ctx.grid.dy == pytest.approx(2.0 / 3.0)
    assert ctx.grid.cell_area == pytest.approx((0.5) * (2.0 / 3.0))


def test_runtime_planar_mesh_samples_domain_surfaces_at_the_cell_centres():
    top = np.full((2, 2), 20.0, dtype=float)
    bottom = np.zeros((2, 2), dtype=float)
    domain = _build_domain_from_dem(top)
    domain.substratum = _build_surface(bottom, name="substratum")
    hydro_mesh = HydroMesh(
        vertices=np.array(
            [
                [0.0, 0.0],
                [1.0, 0.0],
                [1.0, 1.0],
                [0.0, 1.0],
            ],
            dtype=float,
        ),
        cell_blocks=(
            CellBlock(
                CellType.TRIANGLE,
                np.array(
                    [
                        [0, 1, 2],
                        [0, 2, 3],
                    ],
                    dtype=int,
                ),
            ),
        ),
    )
    cell_mesh = cell_mesh_of(hydro_mesh)

    ctx = build_spatial_discretization(
        domain=domain,
        vertical_config=VerticalGridConfig(
            genmtd_lay="constant",
            nlay=1,
            nodata=-9999.0,
        ),
        sgrid_config=SolverSGridConfig(),
        cell_mesh=cell_mesh,
    )

    # Top and botm are sampled from the domain surfaces at the cell centres: every
    # cell takes the DEM top (20) and substratum (0).
    top = ctx.solver_mesh.top.reshape(-1)
    botm = ctx.solver_mesh.botm.reshape(-1)
    assert top.tolist() == pytest.approx([20.0] * top.size)
    assert botm.tolist() == pytest.approx([0.0] * botm.size)


def test_a_triangle_mesh_keeps_its_cells():
    top = np.full((2, 2), 20.0, dtype=float)
    bottom = np.zeros((2, 2), dtype=float)
    domain = _build_domain_from_dem(top)
    domain.substratum = _build_surface(bottom, name="substratum")
    hydro_mesh = HydroMesh(
        vertices=np.array(
            [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]],
            dtype=float,
        ),
        cell_blocks=(CellBlock(CellType.TRIANGLE, np.array([[0, 1, 2], [0, 2, 3]], dtype=int)),),
    )
    cell_mesh = cell_mesh_of(hydro_mesh)

    ctx = build_spatial_discretization(
        domain=domain,
        vertical_config=VerticalGridConfig(genmtd_lay="constant", nlay=1, nodata=-9999.0),
        sgrid_config=SolverSGridConfig(),
        cell_mesh=cell_mesh,
    )

    # The solver grid is the mesh it is given: the 2 triangles, no dual.
    assert ctx.solver_mesh.n_cells == 2


def test_modflow_nwt_refuses_a_cell_mesh_that_is_not_a_regular_grid():
    dem = np.array([[10.0, 11.0], [12.0, 13.0]], dtype=float)
    model = ModflowNwt(geographic=_DummyGeographic(dem), model_folder=".")
    model.domain = _build_domain_from_dem(dem)
    model.cell_mesh = cell_mesh_of(
        HydroMesh(
            vertices=np.array([[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]], dtype=float),
            cell_blocks=(
                CellBlock(CellType.TRIANGLE, np.array([[0, 1, 2], [0, 2, 3]], dtype=int)),
            ),
        )
    )

    with pytest.raises(ValueError, match="requires a structured grid"):
        model._build_spatial_discretization()


def test_modflow_requires_canonical_time_grid_for_launcher_flow_preprocessing():
    dem = np.array([[10.0, 11.0], [12.0, 13.0]], dtype=float)
    geo = _DummyGeographic(dem)
    model = ModflowNwt(geographic=geo, model_folder=".")
    model.flow = SimpleNamespace(config=SimpleNamespace(flow_regime="transient"))
    model.domain = object()
    model.sgrid_config = object()
    model._apply_preprocess_options(model.preprocess_options)
    model.flow.config.flow_regime = "transient"

    with pytest.raises(
        ValueError,
        match=r"preprocess_options\.time_grid derived from \[simulation\.time\] for transient flow runs",
    ):
        model._validate_pre_processing_inputs()


def test_modflow_accepts_missing_time_grid_for_steady_launcher_flow_preprocessing():
    dem = np.array([[10.0, 11.0], [12.0, 13.0]], dtype=float)
    geo = _DummyGeographic(dem)
    model = ModflowNwt(geographic=geo, model_folder=".")
    model.flow = SimpleNamespace(config=SimpleNamespace(flow_regime="steady"))
    model.domain = object()
    model.sgrid_config = object()
    model._apply_preprocess_options(model.preprocess_options)

    # Steady flow should not require a time_grid; method must return None.
    assert model._validate_pre_processing_inputs() is None
