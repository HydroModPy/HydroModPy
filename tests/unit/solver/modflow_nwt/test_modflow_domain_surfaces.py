"""The domain surfaces, the mesh and the time grid ModflowNwt checks before it builds.

A model needs a Domain with its top and substratum on one grid, a structured cell mesh, a raster
geometry and, for a transient run, a time grid. The DEM grid (m) is read off the raster geometry.
"""

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
from hydromodpy.model.model import Geometry, ModelTime
from hydromodpy.solver.modflow_common.options import ModflowPreprocessOptions
from hydromodpy.solver.modflow_nwt.nwt.nwt_solver import ModflowNwt
from tests._helpers.cell_meshes import cell_mesh_of
from tests._helpers.model_factory import make_model, small_geometry


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


def test_domain_object_is_required():
    dem = np.array([[10.0, 11.0], [12.0, 13.0]], dtype=float)

    model = ModflowNwt(model_folder=".")
    model.inputs = _model(dem)
    with pytest.raises(ValueError, match="domain-only: a Domain object is required"):
        model._get_domain_surfaces()


def test_top_and_substratum_are_required():
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


def test_substratum_on_another_grid_is_refused():
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


def test_triangle_mesh_is_refused():
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


def test_transient_run_needs_a_time_grid():
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
def test_model_lacking_a_member_is_refused(members, error, match):
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
def test_dem_grid_from_raster_geometry(box, shape, path):
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
