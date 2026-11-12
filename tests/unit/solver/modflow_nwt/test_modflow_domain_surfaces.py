from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.catchment.raster_support import RasterSupport
from hydromodpy.catchment.surface import Surface
from hydromodpy.core.exceptions import MeshError
from hydromodpy.mesh.planar.cell_types import CellType
from hydromodpy.mesh.planar.hydro_mesh import CellBlock, HydroMesh
from hydromodpy.model.domain.domain import Domain
from hydromodpy.model.domain.domain_config import DomainConfig
from hydromodpy.model.domain.geometry import RasterGeometry
from hydromodpy.model.domain.layers_config import VerticalGridConfig
from hydromodpy.model.model import Geometry, ModelTime
from hydromodpy.solver.modflow_common.options import ModflowPreprocessOptions
from hydromodpy.solver.modflow_grid.discretization_spatial import build_spatial_discretization
from hydromodpy.solver.modflow_grid.sgrid_config import SolverSGridConfig
from hydromodpy.solver.modflow_nwt.nwt.nwt_solver import ModflowNwt
from tests._helpers.cell_meshes import cell_mesh_of
from tests._helpers.model_factory import make_model, small_geometry
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


def _model(dem: np.ndarray, *, domain=None, cells=None, **members):
    """A model on the raster grid of ``dem``, with the domain and the cells given."""
    geometry = Geometry(
        cells=cells,
        domain=domain,
        raster=RasterGeometry.from_geographic(_DummyGeographic(dem)),
    )
    return make_model(geometry=geometry, **members)


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

    model = ModflowNwt(model_folder=".")
    model.inputs = _model(dem)
    with pytest.raises(ValueError, match="domain-only: a Domain object is required"):
        model._get_domain_surfaces()


def test_modflow_domain_surfaces_are_required():
    dem = np.array([[10.0, 11.0], [12.0, 13.0]], dtype=float)
    domain = _build_domain_from_dem(dem)

    domain.substratum = None
    model = ModflowNwt(model_folder=".")
    model.inputs = _model(dem, domain=domain)
    with pytest.raises(
        ValueError,
        match="domain.surface_topo and domain.substratum are required",
    ):
        model._get_domain_surfaces()


def test_modflow_validates_domain_support_match_on_surface_build():
    dem = np.array([[10.0, 11.0], [12.0, 13.0]], dtype=float)
    domain = _build_domain_from_dem(dem)
    domain.substratum = _build_surface(
        np.array([[1.0, 2.0], [3.0, 4.0]], dtype=float),
        xmin=1.0,
        name="substratum",
    )

    model = ModflowNwt(model_folder=".")
    model.inputs = _model(dem, domain=domain)

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

    # Top and botm are sampled from the domain surfaces at the cell centers: every
    # cell takes the DEM top (20) and substratum (0).
    top = ctx.solver_mesh.top.reshape(-1)
    botm = ctx.solver_mesh.botm.reshape(-1)
    assert top.tolist() == pytest.approx([20.0] * top.size)
    assert botm.tolist() == pytest.approx([0.0] * botm.size)


def test_modflow_nwt_refuses_a_cell_mesh_that_is_not_a_regular_grid():
    dem = np.array([[10.0, 11.0], [12.0, 13.0]], dtype=float)
    triangles = cell_mesh_of(
        HydroMesh(
            vertices=np.array([[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]], dtype=float),
            cell_blocks=(
                CellBlock(CellType.TRIANGLE, np.array([[0, 1, 2], [0, 2, 3]], dtype=int)),
            ),
        )
    )
    model = ModflowNwt(model_folder=".")
    model.inputs = _model(dem, domain=_build_domain_from_dem(dem), cells=triangles)

    with pytest.raises(ValueError, match="requires a structured grid"):
        model._build_spatial_discretization()


def test_modflow_requires_canonical_time_grid_for_launcher_flow_preprocessing():
    dem = np.array([[10.0, 11.0], [12.0, 13.0]], dtype=float)
    model = ModflowNwt(model_folder=".")
    model.inputs = _model(
        dem,
        domain=object(),
        cells=small_geometry().cells,
        time=ModelTime(grid=None, regime="transient", first_period_steady=True),
    )
    model._apply_preprocess_options(model.preprocess_options)

    with pytest.raises(
        ValueError,
        match=r"preprocess_options\.time_grid derived from \[simulation\.time\] for transient flow runs",
    ):
        model._validate_pre_processing_inputs()


@pytest.mark.parametrize(
    ("members", "error", "match"),
    [
        ({"inputs": None}, ValueError, "requires a Model"),
        ({"domain": None}, ValueError, "requires a configured Domain object"),
        ({"cells": None}, MeshError, r"Model\.geometry\.cells"),
        ({"raster": None}, ValueError, r"Model\.geometry\.raster is missing"),
    ],
    ids=["no_model", "no_domain", "no_cell_mesh", "no_raster"],
)
def test_pre_processing_refuses_a_model_that_lacks_what_nwt_builds_on(members, error, match):
    model = ModflowNwt(model_folder=".")
    if "inputs" not in members:
        geometry = {"cells": small_geometry().cells, "domain": object(), "raster": object()}
        geometry.update(members)
        model.inputs = make_model(geometry=Geometry(**geometry))
    model._apply_preprocess_options(model.preprocess_options)

    with pytest.raises(error, match=match):
        model._validate_pre_processing_inputs()


@pytest.mark.parametrize(
    ("box", "shape", "path"),
    [(True, (3, 4), "box.tif"), (False, (2, 2), "watershed.tif")],
    ids=["box", "watershed"],
)
def test_the_dem_grid_is_read_off_the_raster_geometry(box, shape, path):
    geographic = _DummyGeographic(np.zeros((2, 2)))
    geographic.dem_box_buff_data = np.zeros((3, 4))
    geographic.dem_res = 25.0
    geographic.xmin, geographic.ymax = 100.0, 200.0
    geographic.watershed_box_buff_dem, geographic.watershed_buff_dem = "box.tif", "watershed.tif"
    model = ModflowNwt(model_folder=".", preprocess_options=ModflowPreprocessOptions(box=box))
    model.inputs = make_model(
        geometry=Geometry(
            cells=None, domain=None, raster=RasterGeometry.from_geographic(geographic)
        )
    )

    model._read_the_dem_grid()

    assert (model.nrow, model.ncol) == shape
    assert model.dem_watershed_path == path
    assert (model.resolution, model.xul, model.yul) == (25.0, 100.0, 200.0)
