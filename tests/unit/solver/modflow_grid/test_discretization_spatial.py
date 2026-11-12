"""Vertical part of the solver mesh (m a.s.l.), built from the DEM, the substratum and the layer bases.

Surfaces are rasters of elevation in m, with -9999 where there is no data. A regular grid or a
planar cell mesh takes its top and bottom from them. A cell that holds a river or a channel can
take the lowest DEM pixel it holds (zonal top), and layers end on the base rasters they name.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from pathlib import Path
from types import SimpleNamespace

import flopy
import numpy as np
import pytest
from flopy.discretization import StructuredGrid
from rasterio.transform import from_bounds

from hydromodpy.catchment.raster_support import RasterSupport
from hydromodpy.catchment.surface import Surface
from hydromodpy.core.exceptions import ConfigError, DataContractViolation, MeshError
from hydromodpy.mesh import registry
from hydromodpy.mesh.cells.zonal_stats import regular_grid_cell_ids, zonal_top
from hydromodpy.mesh.planar.cell_types import CellType
from hydromodpy.mesh.planar.hydro_mesh import CellBlock, HydroMesh
from hydromodpy.mesh.planar.planar_cell_mesh import CellChain, MeshIdentity, build_planar_cell_mesh
from hydromodpy.mesh.request import RasterGridSpec
from hydromodpy.model.domain.domain import Domain
from hydromodpy.model.domain.domain_config import DomainConfig
from hydromodpy.model.domain.layers_config import VerticalGridConfig
from hydromodpy.model.model import Geometry
from hydromodpy.solver.modflow_grid.discretization_spatial import (
    StructuredGridBuilder,
    _build_extruded_solver_mesh_from_runtime_planar,
    build_spatial_discretization,
)
from hydromodpy.solver.modflow_grid.sgrid_config import SolverSGridConfig, TopSamplingConfig
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh
from hydromodpy.solver.modflow_nwt.nwt.nwt_solver import ModflowNwt
from tests._helpers.cell_meshes import TEST_CRS_WKT, cell_mesh_of
from tests._helpers.mesh_cases import mesh_request
from tests._helpers.model_factory import make_model
from tests._helpers.regular_cell_meshes import regular_cell_mesh, regular_cell_mesh_of_surface
from tests._helpers.solver_meshes import solver_mesh_from_sgrid

NODATA = -9999.0


def raster(
    values,
    *,
    xmin: float = 0.0,
    ymin: float = 0.0,
    dx: float = 1.0,
    dy: float = 1.0,
    crs: str | None = "EPSG:2154",
    nodata: float = NODATA,
    name: str = "surface",
) -> Surface:
    arr = np.asarray(values, dtype=float)
    nrows, ncols = arr.shape
    support = RasterSupport(
        crs=crs,
        dx=dx,
        dy=dy,
        xmin=xmin,
        xmax=xmin + dx * ncols,
        ymin=ymin,
        ymax=ymin + dy * nrows,
        nrows=nrows,
        ncols=ncols,
        nodata=nodata,
    )
    return Surface(name=name, values=arr, support=support)


def with_support(surface: Surface, **changes: object) -> Surface:
    """The same surface on a support with the changes."""
    return Surface(
        name=surface.name, values=surface.as_array(), support=replace(surface.support, **changes)
    )


def domain_of(top: Surface, bottom: Surface | None = None, config=None) -> Domain:
    domain = Domain(config=config or DomainConfig(), surface_topo=top)
    if bottom is not None:
        domain.substratum = bottom
    return domain


# Vertical part of a regular grid, from the two surfaces (StructuredGridBuilder).

TOP = np.array([[120.0, 121.0], [122.0, 123.0]])  # m
BOTTOM = np.array([[20.0, 21.0], [22.0, 23.0]])  # m
TWO_LAYERS = {"genmtd_lay": "constant", "nlay": 2}
WEATHERED_BASE_LAYERS = VerticalGridConfig(
    genmtd_lay="surfaces",
    layer=[{"name": "weathered", "surface": "weathered_base"}, {"name": "fissured"}],
)


def build_grid(top: Surface, bottom: Surface, **kwargs):
    kwargs.setdefault("vertical_config", TWO_LAYERS)
    return StructuredGridBuilder().build_from_surfaces(
        top_surface=top, bottom_surface=bottom, **kwargs
    )


def test_absolute_top_and_bottom():
    sgrid = build_grid(
        raster(TOP, name="top"),
        raster(BOTTOM, name="bottom"),
        vertical_config=VerticalGridConfig(genmtd_lay="constant", nlay=3, nodata=NODATA),
    )

    assert sgrid.nlay == 3
    np.testing.assert_allclose(sgrid.top, TOP)
    np.testing.assert_allclose(sgrid.botm[-1], BOTTOM)


def test_support_without_steps_is_accepted():
    top = with_support(raster(TOP, dx=4.0, dy=3.0), dx=None, dy=None)

    sgrid = build_grid(top, raster(BOTTOM, dx=4.0, dy=3.0))

    assert sgrid.nlay == 2
    np.testing.assert_allclose(sgrid.top, TOP)


def test_layers_end_on_their_base_surfaces():
    base = np.array([[70.0, 71.0], [72.0, 73.0]])

    sgrid = build_grid(
        raster(TOP),
        raster(BOTTOM),
        vertical_config=WEATHERED_BASE_LAYERS,
        base_surfaces={"weathered_base": raster(base, name="weathered_base")},
    )

    assert sgrid.nlay == 2
    np.testing.assert_allclose(sgrid.botm[0], base)
    np.testing.assert_allclose(sgrid.botm[1], BOTTOM)


def test_nodata_cell_outside():
    top = TOP.copy()
    top[0, 1] = NODATA

    sgrid = build_grid(raster(top), raster(BOTTOM))

    assert np.all(sgrid.idomain[:, 0, 1] == 0)
    assert np.all(sgrid.idomain[:, [0, 1, 1], [0, 0, 1]] == 1)
    assert np.all(sgrid.botm[:, 0, 1] == NODATA)


# One row per cell state in the top and bottom surfaces: the nodata of the vertical
# config, the values of the cell, and whether it is inside the domain (1) or not (0).
NODATA_CELLS = [
    pytest.param(NODATA, 120.0, 20.0, 1, id="valid cell"),
    pytest.param(NODATA, NODATA, 20.0, 0, id="top is nodata"),
    pytest.param(NODATA, 120.0, NODATA, 0, id="bottom is nodata"),
    pytest.param(NODATA, np.nan, 20.0, 0, id="top is nan"),
    pytest.param(NODATA, 120.0, np.nan, 0, id="bottom is nan"),
    pytest.param(NODATA, -1.0e30, 20.0, 0, id="top far below the sentinel"),
    pytest.param(-32768.0, -32768.0, 20.0, 0, id="chosen nodata is read"),
    pytest.param(-32768.0, -9990.0, NODATA, 1, id="default value is data under a chosen nodata"),
]


@pytest.mark.parametrize(("nodata", "top_value", "bottom_value", "idomain"), NODATA_CELLS)
def test_nodata_cell_is_inactive(nodata, top_value, bottom_value, idomain):
    top, bottom = TOP.copy(), BOTTOM.copy()
    top[0, 1] = top_value
    bottom[0, 1] = bottom_value

    sgrid = build_grid(
        raster(top, nodata=nodata),
        raster(bottom, nodata=nodata),
        vertical_config=VerticalGridConfig(genmtd_lay="constant", nlay=2, nodata=nodata),
    )

    assert np.all(sgrid.idomain[:, 0, 1] == idomain)
    assert np.all(sgrid.idomain[:, 0, 0] == 1)
    if idomain == 0:
        assert np.all(sgrid.botm[:, 0, 1] == nodata)


FLIPPED = {"dx": None, "dy": None, "xmin": 8.0, "xmax": 0.0}
GRID_REFUSALS = [
    pytest.param(
        raster(TOP, name="top"),
        raster(BOTTOM, xmin=1.0, name="bottom"),
        {},
        "Domain extent mismatch",
        id="extents differ",
    ),
    pytest.param(
        with_support(raster(TOP, ymin=100.0, dx=4.0, dy=3.0), **FLIPPED),
        with_support(raster(BOTTOM, ymin=100.0, dx=4.0, dy=3.0), **FLIPPED),
        {},
        r"Invalid support cell sizes: dx=-4.0, dy=3.0",
        id="steps read off a flipped extent",
    ),
    pytest.param(
        raster(TOP),
        raster(BOTTOM),
        {
            "vertical_config": WEATHERED_BASE_LAYERS,
            "base_surfaces": {"weathered_base": raster(np.full((1, 1), 70.0), dx=2.0, dy=2.0)},
        },
        r"layer base 'weathered_base' has shape \(1, 1\), the top \(2, 2\)",
        id="layer base on another grid",
    ),
    pytest.param(
        raster(TOP),
        raster(np.full((4, 4), 20.0), dx=0.5, dy=0.5),
        {},
        r"must have the same discretization.*resample_to_shape",
        id="bottom on another grid",
    ),
    # A north-up raster transform carries a negative y step. The support must not.
    pytest.param(
        with_support(raster(TOP), dx=-1.0),
        raster(BOTTOM),
        {},
        r"Invalid support cell sizes: dx=-1.0, dy=1.0",
        id="negative dx",
    ),
    pytest.param(
        with_support(raster(TOP), dy=-1.0),
        raster(BOTTOM),
        {},
        r"Invalid support cell sizes: dx=1.0, dy=-1.0",
        id="negative dy",
    ),
]


@pytest.mark.parametrize(("top", "bottom", "kwargs", "match"), GRID_REFUSALS)
def test_grid_refusals(top, bottom, kwargs, match):
    with pytest.raises(ValueError, match=match):
        build_grid(top, bottom, **kwargs)


# A regular grid and a planar cell mesh on the DEM resample or sample it on their cells.


def test_resamples_to_the_mesh_shape():
    domain = domain_of(raster([[20.0, 22.0], [24.0, 26.0]], name="surface_topo"))

    ctx = build_spatial_discretization(
        domain=domain,
        vertical_config=VerticalGridConfig(genmtd_lay="constant", nlay=2, nodata=NODATA),
        sgrid_config=SolverSGridConfig(),
        cell_mesh=regular_cell_mesh_of_surface(domain.surface_topo, nrow=3, ncol=4),
    )

    assert (ctx.nrow, ctx.ncol) == (3, 4)
    assert ctx.top_elevation.shape == (12,)
    assert ctx.bottom_layer.shape == (12,)
    assert ctx.solver_mesh.botm.shape == (2, 12)
    assert ctx.grid.dx == pytest.approx(0.5)  # 2 m over 4 columns
    assert ctx.grid.dy == pytest.approx(2.0 / 3.0)  # 2 m over 3 rows
    assert ctx.grid.cell_area == pytest.approx(0.5 * 2.0 / 3.0)


def test_planar_mesh_cell_centres():
    domain = domain_of(
        raster(np.full((2, 2), 20.0), name="surface_topo"),
        raster(np.zeros((2, 2)), name="substratum"),
    )
    square_in_triangles = HydroMesh(
        vertices=np.array([[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]),
        cell_blocks=(CellBlock(CellType.TRIANGLE, np.array([[0, 1, 2], [0, 2, 3]])),),
    )

    ctx = build_spatial_discretization(
        domain=domain,
        vertical_config=VerticalGridConfig(genmtd_lay="constant", nlay=1, nodata=NODATA),
        sgrid_config=SolverSGridConfig(),
        cell_mesh=cell_mesh_of(square_in_triangles),
    )

    # Every cell takes the DEM top (20 m) and the substratum (0 m).
    np.testing.assert_allclose(ctx.solver_mesh.top.reshape(-1), 20.0)
    np.testing.assert_allclose(ctx.solver_mesh.botm.reshape(-1), 0.0)


# A regular mesh is extruded on the surfaces only if both describe one grid. A mesh shifted
# by a meter, a step off by a part in a million, or a mesh that forgets its shape would move
# every cell against its elevation without an array mismatch, so the builder refuses them.

EXTRUDE_N = 6
EXTRUDE_STEP_M = 40.0
EXTRUDE_XMIN, EXTRUDE_YMIN = 1_000.0, 2_000.0


def extrude(cell_mesh):
    def flat(name, value):
        return raster(
            np.full((EXTRUDE_N, EXTRUDE_N), value),
            xmin=EXTRUDE_XMIN,
            ymin=EXTRUDE_YMIN,
            dx=EXTRUDE_STEP_M,
            dy=EXTRUDE_STEP_M,
            name=name,
        )

    return build_spatial_discretization(
        domain=domain_of(flat("surface_topo", 20.0), flat("substratum", 0.0)),
        vertical_config=VerticalGridConfig(nlay=1, nodata=NODATA),
        sgrid_config=SolverSGridConfig(),
        cell_mesh=cell_mesh,
    )


def extrusion_mesh(**changes: float):
    grid = {
        "xmin": EXTRUDE_XMIN,
        "ymin": EXTRUDE_YMIN,
        "dx": EXTRUDE_STEP_M,
        "dy": EXTRUDE_STEP_M,
        "nrow": EXTRUDE_N,
        "ncol": EXTRUDE_N,
    }
    return regular_cell_mesh(**{**grid, **changes})


def mesh_without_its_shape():
    cell_mesh = extrusion_mesh()
    return replace(cell_mesh, mesh=replace(cell_mesh.mesh, structured_shape=None))


def test_other_mesh_shape_resamples():
    n_rows, n_cols = EXTRUDE_N // 3, EXTRUDE_N // 2

    ctx = extrude(
        extrusion_mesh(dx=EXTRUDE_STEP_M * 2, dy=EXTRUDE_STEP_M * 3, nrow=n_rows, ncol=n_cols)
    )

    assert ctx.solver_mesh.structured_shape == (n_rows, n_cols)
    assert ctx.top_surface.as_array().shape == (n_rows, n_cols)
    np.testing.assert_allclose(ctx.solver_mesh.top, 20.0)


EXTRUSION_REFUSALS = [
    pytest.param(extrusion_mesh(xmin=EXTRUDE_XMIN + 1.0), "differ", id="shifted east"),
    pytest.param(extrusion_mesh(ymin=EXTRUDE_YMIN - 1.0), "differ", id="shifted south"),
    pytest.param(extrusion_mesh(dx=EXTRUDE_STEP_M * (1.0 + 1e-6)), "differ", id="wider cells"),
    pytest.param(extrusion_mesh(dy=EXTRUDE_STEP_M * (1.0 - 1e-6)), "differ", id="shorter cells"),
    pytest.param(mesh_without_its_shape(), "shape", id="no structured shape"),
]


@pytest.mark.parametrize(("cell_mesh", "match"), EXTRUSION_REFUSALS)
def test_extrusion_refusals(cell_mesh, match):
    with pytest.raises(MeshError, match=match):
        extrude(cell_mesh)


# A regular grid gives the solvers the grid the flopy round trip gave them. The input files
# of MODFLOW-NWT (DIS) and MODFLOW 6 (DISV) must not move by one bit.


@dataclass(frozen=True)
class RegularGrid:
    nrow: int
    ncol: int
    xmin: float
    ymin: float
    dx: float
    dy: float
    shape: tuple[int, int] | None = None  # mesh shape when it differs from the DEM


REGULAR_GRIDS = [
    pytest.param(RegularGrid(7, 5, 1234.567, 7654.321, 12.3, 12.3), id="non integer step"),
    pytest.param(RegularGrid(5, 9, -1500.25, -830.5, 3.3, 3.3), id="negative origin"),
    pytest.param(RegularGrid(1, 40, 0.0, 0.0, 25.0, 25.0), id="band 1 by 40"),
    pytest.param(RegularGrid(6, 8, 372_337.5, 6_788_912.5, 75.0, 75.0), id="native 75 m"),
    pytest.param(
        RegularGrid(12, 12, 100.0, -40.0, 25.0, 25.0, shape=(4, 3)), id="coarser than the dem"
    ),
]


def regular_surface(grid: RegularGrid, values, name: str) -> Surface:
    return raster(values, xmin=grid.xmin, ymin=grid.ymin, dx=grid.dx, dy=grid.dy, name=name)


def regular_domain(grid: RegularGrid) -> Domain:
    top = 50.0 + np.random.default_rng(11).uniform(0.0, 20.0, size=(grid.nrow, grid.ncol))
    if grid.nrow * grid.ncol > 4:
        top[0, 0] = NODATA
    return domain_of(
        regular_surface(grid, top, "surface_topo"),
        regular_surface(grid, np.full(top.shape, 10.0), "substratum"),
    )


def engine_mesh(grid: RegularGrid, domain: Domain):
    spec = RasterGridSpec.from_raster_support(domain.surface_topo.support, crs_wkt=TEST_CRS_WKT)
    options = {} if grid.shape is None else {"shape": list(grid.shape)}
    request = mesh_request(spec, nominal_size_m=grid.dx, options=options)
    return registry.mesh_engines.create("regular").build(request)


def flopy_round_trip_mesh(grid: RegularGrid, domain: Domain, vertical) -> SolverMesh:
    """The solver mesh of the flopy round trip, as the code built it before the unified mesh."""
    top_surface, bottom_surface = domain.surface_topo, domain.substratum
    if grid.shape is not None:
        top_surface, bottom_surface = (
            s.resample_to_shape(*grid.shape, resampling="bilinear", nodata=NODATA, name=s.name)
            for s in (top_surface, bottom_surface)
        )
    top = np.asarray(top_surface.as_array(), dtype=float)
    bottom = np.asarray(bottom_surface.as_array(), dtype=float)
    spec = build_grid(top_surface, bottom_surface, vertical_config=vertical)
    support = top_surface.support
    nrow, ncol = int(support.nrows), int(support.ncols)
    xmin, xmax = float(support.xmin), float(support.xmax)
    ymin, ymax = float(support.ymin), float(support.ymax)
    dx = float(support.dx) if support.dx is not None else (xmax - xmin) / ncol
    dy = float(support.dy) if support.dy is not None else (ymax - ymin) / nrow
    sgrid = StructuredGrid(
        delc=np.full(nrow, dy, dtype=float),
        delr=np.full(ncol, dx, dtype=float),
        top=spec.top,
        botm=spec.botm,
        xoff=xmin,
        yoff=ymin,
        nlay=spec.nlay,
        nrow=nrow,
        ncol=ncol,
        crs=support.crs,
    )
    inactive = ~np.isfinite(top) | ~np.isfinite(bottom) | (top <= NODATA) | (bottom <= NODATA)
    return solver_mesh_from_sgrid(
        sgrid, zbot=np.asarray(sgrid.botm, dtype=float), inactive_mask=inactive
    )


def write_dis(solver_mesh: SolverMesh, folder: Path) -> str:
    """Write the DIS file the way ``ModflowNwt._build_dis_package`` does and read it back."""
    vertices = np.asarray(solver_mesh.planar_mesh.vertices, dtype=float)
    model = flopy.modflow.Modflow("dis", model_ws=str(folder))
    dis = flopy.modflow.ModflowDis(
        model,
        lenuni=2,
        xul=float(vertices[:, 0].min()),
        yul=float(vertices[:, 1].max()),
        **solver_mesh.to_dis_kwargs(),
        itmuni=4,
        nper=1,
        perlen=[1.0],
        nstp=[1],
        steady=[True],
    )
    dis.write_file()
    return (folder / "dis.dis").read_text()


def write_disv(solver_mesh: SolverMesh, folder: Path) -> str:
    """Write the MODFLOW 6 DISV file and read it back, without its time stamp."""
    sim = flopy.mf6.MFSimulation(sim_name="disv", sim_ws=str(folder), exe_name="mf6")
    flopy.mf6.ModflowTdis(sim, nper=1, perioddata=[(1.0, 1, 1.0)])
    gwf = flopy.mf6.ModflowGwf(sim, modelname="disv")
    flopy.mf6.ModflowGwfdisv(gwf, length_units="METERS", **solver_mesh.to_disv_kwargs())
    sim.write_simulation(silent=True)
    lines = (folder / "disv.disv").read_text().splitlines(keepends=True)
    return "".join(line for line in lines if not line.startswith("# File generated by Flopy"))


@pytest.mark.parametrize("grid", REGULAR_GRIDS)
def test_dis_and_disv_unchanged(grid: RegularGrid, tmp_path: Path):
    domain = regular_domain(grid)
    vertical = VerticalGridConfig(genmtd_lay="constant", nlay=2, nodata=NODATA)
    before = flopy_round_trip_mesh(grid, domain, vertical)

    now = build_spatial_discretization(
        domain=domain,
        vertical_config=vertical,
        sgrid_config=SolverSGridConfig(),
        cell_mesh=engine_mesh(grid, domain),
    ).solver_mesh

    assert now.is_structured
    assert now.structured_shape == before.structured_shape
    assert np.array_equal(now.planar_mesh.vertices, before.planar_mesh.vertices)
    assert np.array_equal(now.planar_mesh.flat_connectivity, before.planar_mesh.flat_connectivity)
    assert np.array_equal(now.top, before.top)
    assert np.array_equal(now.botm, before.botm)
    assert np.array_equal(now.inactive_mask, before.inactive_mask)
    assert write_dis(now, tmp_path / "now_dis") == write_dis(before, tmp_path / "before_dis")
    assert write_disv(now, tmp_path / "now_disv") == write_disv(before, tmp_path / "before_disv")


# A layering by surfaces goes from the domain rasters to the solver mesh. The weathered
# layer thins out to the east and pinches into pass-through cells (idomain -1) whose
# thickness the layer below takes.

LAYER_ROWS, LAYER_COLS = 4, 6
LAYER_STEP_M = 100.0
WEATHERED_M = np.linspace(8.0, 0.0, LAYER_COLS)  # thickness of the weathered layer by column
SURFACE_LAYERS = {
    "genmtd_lay": "surfaces",
    "layer": [
        {"name": "weathered", "surface": "weathered_base", "min_thickness": 1.0},
        {"name": "fissured", "thickness": 20.0},
        {"name": "rock"},
    ],
}


def layered_surface(values, name: str) -> Surface:
    return raster(values, dx=LAYER_STEP_M, dy=LAYER_STEP_M, name=name)


def layered_top() -> Surface:
    return layered_surface(np.full((LAYER_ROWS, LAYER_COLS), 100.0), "surface_topo")


def layered_domain(base: np.ndarray | None = None) -> Domain:
    weathered_base = (
        np.full((LAYER_ROWS, LAYER_COLS), 100.0) - WEATHERED_M[None, :] if base is None else base
    )
    return Domain(
        config=DomainConfig.model_validate(
            {
                "depth_model": {"kind": "constant_thickness", "thickness": 60.0},
                "layers": SURFACE_LAYERS,
            }
        ),
        surface_topo=layered_top(),
        layer_base_sources={"weathered_base": layered_surface(weathered_base, "w")},
    )


def regular_layered_cells(domain: Domain):
    spec = RasterGridSpec.from_raster_support(domain.surface_topo.support, crs_wkt=TEST_CRS_WKT)
    return registry.mesh_engines.create("regular").build(mesh_request(spec))


def triangle_layered_cells():
    xs = np.linspace(50.0, LAYER_STEP_M * LAYER_COLS - 50.0, LAYER_COLS)
    ys = np.linspace(50.0, LAYER_STEP_M * LAYER_ROWS - 50.0, LAYER_ROWS)
    node_x, node_y = (a.reshape(-1) for a in np.meshgrid(xs, ys))
    triangles = []
    for j in range(LAYER_ROWS - 1):
        for i in range(LAYER_COLS - 1):
            a, b = j * LAYER_COLS + i, j * LAYER_COLS + i + 1
            c, d = (j + 1) * LAYER_COLS + i + 1, (j + 1) * LAYER_COLS + i
            triangles.extend([(a, b, c), (a, c, d)])
    mesh = HydroMesh(
        vertices=np.column_stack([node_x, node_y]),
        cell_blocks=(CellBlock(CellType.TRIANGLE, np.asarray(triangles, dtype=int)),),
    )
    return cell_mesh_of(mesh)


def layered_solver_mesh(domain: Domain, cell_mesh) -> SolverMesh:
    return build_spatial_discretization(
        domain=domain,
        vertical_config=domain.config.layers,
        sgrid_config=None,
        cell_mesh=cell_mesh,
    ).solver_mesh


def test_layer_base_on_top_grid():
    domain = layered_domain()

    assert list(domain.layer_bases) == ["weathered_base"]
    np.testing.assert_allclose(
        domain.layer_bases["weathered_base"].as_array()[0], 100.0 - WEATHERED_M
    )


def test_domain_refusals():
    with pytest.raises(ConfigError, match="none was given to the domain"):
        Domain(
            config=DomainConfig.model_validate({"layers": SURFACE_LAYERS}),
            surface_topo=layered_top(),
        )

    base = np.full((LAYER_ROWS, LAYER_COLS), 95.0)
    base[1, 2] = np.nan
    with pytest.raises(DataContractViolation, match="leaves 1 of the 24 cells"):
        layered_domain(base)


def test_weathered_layer_pinches_out():
    domain = layered_domain()

    mesh = layered_solver_mesh(domain, regular_layered_cells(domain))

    idomain = mesh.idomain.reshape(3, LAYER_ROWS, LAYER_COLS)
    thin = WEATHERED_M < 1.0
    assert (idomain[0][:, thin] == -1).all()
    assert (idomain[0][:, ~thin] == 1).all()
    assert (idomain[1:] == 1).all()
    botm = mesh.botm.reshape(3, LAYER_ROWS, LAYER_COLS)
    np.testing.assert_allclose(botm[0][0], np.where(thin, 100.0, 100.0 - WEATHERED_M))
    np.testing.assert_allclose(botm[1][0], 100.0 - WEATHERED_M - 20.0)
    np.testing.assert_allclose(botm[2], 40.0)


def test_triangle_mesh_samples_base():
    cell_mesh = triangle_layered_cells()

    mesh = layered_solver_mesh(layered_domain(), cell_mesh)

    weathered = np.interp(
        cell_mesh.centers[:, 0], 50.0 + LAYER_STEP_M * np.arange(LAYER_COLS), WEATHERED_M
    )
    thin = weathered < 1.0
    assert thin.any() and (~thin).any()
    np.testing.assert_array_equal(mesh.idomain[0], np.where(thin, -1, 1))
    np.testing.assert_allclose(mesh.layer_thicknesses()[0][~thin], weathered[~thin], atol=1e-6)
    np.testing.assert_allclose(mesh.layer_thicknesses()[1][thin], 20.0 + weathered[thin], atol=1e-6)


def test_nwt_refuses_pass_through_cells():
    domain = layered_domain()
    geometry = Geometry(cells=regular_layered_cells(domain), domain=domain)
    solver = SimpleNamespace(inputs=make_model(geometry=geometry), sgrid_config=None)

    with pytest.raises(ConfigError, match="MODFLOW-NWT does not have"):
        ModflowNwt._build_spatial_discretization(solver)


# Centroid top, and a river cell lowered to the lowest DEM pixel it holds. Two cells
# side by side (x 0-50 m and 50-100 m) on a DEM ramp z = x over 40 x 40 pixels of 2.5 m.
# A notch (the river bed, 0.5 m) lies in cell 0 off its center, so the centroid sample of
# cell 0 lands on the ramp. A river chain with a lateral offset above zero marks the cell as
# a crossing cell, and only that cell is lowered to the notch.

DEM_EXTENT_M = 100.0
DEM_N = 40
DEM_PIXEL_M = DEM_EXTENT_M / DEM_N
PIXEL_X_M = (np.arange(DEM_N) + 0.5) * DEM_PIXEL_M
THALWEG_M = 0.5
NOTCH_COLUMNS = (PIXEL_X_M >= 10.0) & (PIXEL_X_M <= 15.0)


def ramp_dem(notch_m: float | None = None) -> np.ndarray:
    dem = np.tile(PIXEL_X_M, (DEM_N, 1))
    if notch_m is not None:
        dem[:, NOTCH_COLUMNS] = notch_m
    return dem


def two_quads() -> HydroMesh:
    vertices = np.array(
        [[0.0, 0.0], [50.0, 0.0], [100.0, 0.0], [0.0, 100.0], [50.0, 100.0], [100.0, 100.0]]
    )
    connectivity = np.array([[0, 1, 4, 3], [1, 2, 5, 4]])
    return HydroMesh(
        vertices=vertices, cell_blocks=(CellBlock(CellType.QUADRILATERAL, connectivity),)
    )


def river_chain(cells, offsets) -> CellChain:
    return CellChain(
        "rivers", 0, np.asarray(cells), None if offsets is None else np.asarray(offsets)
    )


def extrude_quads(*, chains=(), dem=None, bottom=-10.0, top_sampling=None, channel_mask=None):
    hydro = two_quads()
    x, y = hydro.cell_centroids()
    cell_mesh = build_planar_cell_mesh(
        hydro,
        np.column_stack([x, y]),
        center_kind="vertex_mean",
        crs_wkt=TEST_CRS_WKT,
        identity=MeshIdentity("test", "0", "", None),
        declarations={
            "graded": False,
            "exact_faces": False,
            "deterministic": True,
            "needs_cache": False,
        },
        cell_chains=chains,
    )

    def dem_surface(values, name):
        return raster(values, dx=DEM_PIXEL_M, dy=DEM_PIXEL_M, crs=None, name=name)

    return _build_extruded_solver_mesh_from_runtime_planar(
        cell_mesh=cell_mesh,
        top_surface=dem_surface(ramp_dem(THALWEG_M) if dem is None else dem, "top"),
        bottom_surface=dem_surface(np.full((DEM_N, DEM_N), bottom), "bot"),
        vertical_config=VerticalGridConfig(),
        nodata=NODATA,
        top_sampling=top_sampling,
        channel_mask=channel_mask,
    )


CENTROID_HALF_METER = TopSamplingConfig(mode="centroid", min_thickness_m=0.5)


def test_centroid_mode_is_baseline():
    baseline = extrude_quads(dem=ramp_dem(), top_sampling=None)
    centroid = extrude_quads(dem=ramp_dem(), top_sampling=TopSamplingConfig(mode="centroid"))

    np.testing.assert_array_equal(baseline.top, centroid.top)
    # The generators sit at x = 25 and 75 on the z = x ramp.
    assert baseline.top == pytest.approx([25.0, 75.0], abs=1.0)


def test_crossing_cell_lowered():
    baseline = extrude_quads()
    crossing = extrude_quads(chains=(river_chain([0, 1], [8.0, 0.0]),))

    assert baseline.top[0] == pytest.approx(25.0, abs=1.0)
    assert crossing.top[0] == pytest.approx(THALWEG_M, abs=1e-6)


@pytest.mark.parametrize("offsets", [None, [0.0, 0.0]], ids=["no offset", "zero offset"])
def test_chain_without_lateral_offset_changes_nothing(offsets):
    held = extrude_quads(chains=(river_chain([0, 1], offsets),))

    np.testing.assert_array_equal(held.top, extrude_quads().top)


def test_lowered_top_drags_bottom():
    # The notch is far under the center sample: the column keeps its center-sample thickness.
    bottom = THALWEG_M - 0.1
    baseline = extrude_quads(top_sampling=CENTROID_HALF_METER, bottom=bottom)
    crossing = extrude_quads(
        chains=(river_chain([0], [8.0]),), top_sampling=CENTROID_HALF_METER, bottom=bottom
    )

    assert crossing.top[0] == pytest.approx(THALWEG_M, abs=1e-6)
    assert crossing.top[0] - crossing.botm[-1, 0] == pytest.approx(
        baseline.top[0] - baseline.botm[-1, 0]
    )
    assert crossing.botm[-1, 0] < bottom
    np.testing.assert_array_equal(crossing.botm[:, 1], baseline.botm[:, 1])


def test_clear_lowered_top_keeps_bottom():
    baseline = extrude_quads(top_sampling=CENTROID_HALF_METER)
    crossing = extrude_quads(chains=(river_chain([0], [8.0]),), top_sampling=CENTROID_HALF_METER)

    assert crossing.top[0] == pytest.approx(THALWEG_M, abs=1e-6)
    np.testing.assert_array_equal(crossing.botm[-1], baseline.botm[-1])


def test_unlowered_cell_keeps_a_thin_column():
    # A bottom within the minimum thickness of an unlowered top is not this guard's business.
    thin = extrude_quads(top_sampling=CENTROID_HALF_METER, bottom=24.9)

    assert thin.botm[-1, 0] == pytest.approx(24.9)


def test_pit_keeps_zonal_column():
    # A channel pixel 60 m under the center sample must not leave a column of 0.1 m.
    dem = ramp_dem()
    dem[4:8, 2:6] = -60.0
    zonal = extrude_quads(
        dem=dem,
        bottom=0.0,
        top_sampling=TopSamplingConfig(mode="zonal", channel_source="none", min_thickness_m=0.1),
        channel_mask=dem < -50.0,
    )
    centre = extrude_quads(dem=dem, bottom=0.0)

    assert zonal.top[0] == pytest.approx(-60.0)
    assert zonal.top[0] - zonal.botm[-1, 0] == pytest.approx(centre.top[0])
    assert zonal.top[1] - zonal.botm[-1, 1] > 1.0


@pytest.mark.parametrize(
    ("lowering_share", "follows"),
    [(0.95, True), (0.80, False)],
    ids=["leaves 5 percent", "leaves 20 percent"],
)
def test_thin_column_restored(lowering_share, follows):
    # The notch removes 95 % of the 25 m center column (0.5 m < 10 % of it) but not 80 %.
    config = TopSamplingConfig(mode="centroid", min_thickness_m=0.1)
    centre_column = extrude_quads(top_sampling=config, bottom=0.0).top[0]
    dem = ramp_dem(THALWEG_M)
    dem[:, PIXEL_X_M <= 15.0] = (1.0 - lowering_share) * centre_column

    crossing = extrude_quads(
        chains=(river_chain([0], [8.0]),), top_sampling=config, bottom=0.0, dem=dem
    )

    column = crossing.top[0] - crossing.botm[-1, 0]
    expected = centre_column if follows else (1.0 - lowering_share) * centre_column
    assert column == pytest.approx(expected)


def test_zonal_channel_minimum():
    dem = ramp_dem(5.0)  # off-center channel in cell 0
    zonal = extrude_quads(
        dem=dem,
        top_sampling=TopSamplingConfig(mode="zonal", channel_stat="min", spike_guard_tol_m=0.0),
        channel_mask=np.tile(NOTCH_COLUMNS, (DEM_N, 1)),
    )

    # Cell 0 carries the channel, its top drops to the thalweg. Cell 1 stays on the ramp.
    assert zonal.top[0] == pytest.approx(5.0, abs=1e-3)
    assert zonal.top[1] == pytest.approx(75.0, abs=2.0)


# Zonal top on a structured grid coarser than its DEM. A 12 x 12 DEM of 25 m pixels is
# resampled to a 4 x 4 grid of 75 m cells, so every cell holds a 3 x 3 block of pixels. In
# zonal mode a channel cell takes the minimum of its block and a hillslope cell the median.

PIXEL_M = 25.0
DEM_SIDE = 12
BLOCK = 3
BLOCKS_PER_SIDE = DEM_SIDE // BLOCK
ONE_LAYER = VerticalGridConfig(nlay=1, nodata=NODATA)


def hill_dem() -> np.ndarray:
    """A plane sloping east, plus a flat spike-free relief inside every block."""
    rng = np.random.default_rng(3)
    base = 100.0 + 0.02 * np.arange(DEM_SIDE)[None, :] * PIXEL_M
    return base + rng.uniform(0.0, 0.5, size=(DEM_SIDE, DEM_SIDE))


def hill_surface(values, name: str) -> Surface:
    return raster(values, dx=PIXEL_M, dy=PIXEL_M, name=name)


def block_grid(n: int = BLOCKS_PER_SIDE):
    """The regular mesh of ``n x n`` cells over the extent of the DEM."""
    return regular_cell_mesh_of_surface(
        hill_surface(np.zeros((DEM_SIDE, DEM_SIDE)), "surface_topo"), nrow=n, ncol=n
    )


def pixel_blocks(array: np.ndarray) -> np.ndarray:
    """The 9 pixels of every 75 m cell, as (4, 4, 9)."""
    n = BLOCKS_PER_SIDE
    return array.reshape(n, BLOCK, n, BLOCK).transpose(0, 2, 1, 3).reshape(n, n, -1)


def channel_pixels() -> np.ndarray:
    """One channel pixel in cell (1, 2) and a full column of them in cell (3, 0)."""
    mask = np.zeros((DEM_SIDE, DEM_SIDE), dtype=bool)
    mask[4, 7] = True
    mask[9:12, 1] = True
    return mask


def zonal_discretization(
    dem, top_sampling, *, n_cells=BLOCKS_PER_SIDE, channel_mask=None, bottom=0.0
):
    return build_spatial_discretization(
        vertical_config=ONE_LAYER,
        domain=domain_of(
            hill_surface(dem, "surface_topo"),
            hill_surface(np.full(dem.shape, bottom), "substratum"),
        ),
        sgrid_config=SolverSGridConfig(top_sampling=top_sampling),
        cell_mesh=block_grid(n_cells),
        channel_mask=channel_mask,
    )


def block_tops(ctx) -> np.ndarray:
    n = BLOCKS_PER_SIDE
    return np.asarray(ctx.solver_mesh.top, dtype=float).reshape(n, n)


def test_zonal_minimum_and_median():
    dem = hill_dem()
    dem[4, 7] -= 4.0  # incised thalweg pixel, inside cell (1, 2)
    dem[9:12, 1] -= 3.0
    mask = channel_pixels()

    ctx = zonal_discretization(
        dem, TopSamplingConfig(mode="zonal", spike_guard_tol_m=0.0), channel_mask=mask
    )

    top = block_tops(ctx)
    pixels = pixel_blocks(dem)
    channel = pixel_blocks(mask).any(axis=-1)
    assert channel.sum() == 2
    for row in range(top.shape[0]):
        for col in range(top.shape[1]):
            if channel[row, col]:
                expected = pixels[row, col][pixel_blocks(mask)[row, col]].min()
            else:
                expected = np.median(pixels[row, col])
            assert top[row, col] == pytest.approx(expected)


def test_dem_shape_mesh_unchanged():
    dem = hill_dem()
    plain = zonal_discretization(dem, TopSamplingConfig(), n_cells=DEM_SIDE)
    zonal = zonal_discretization(
        dem, TopSamplingConfig(mode="zonal"), n_cells=DEM_SIDE, channel_mask=channel_pixels()
    )

    np.testing.assert_array_equal(plain.solver_mesh.top, zonal.solver_mesh.top)
    np.testing.assert_array_equal(plain.solver_mesh.top, dem.reshape(-1))


def test_pixel_grid_keeps_values():
    dem = hill_dem()
    dem[4, 7] -= 4.0

    ctx = zonal_discretization(
        dem, TopSamplingConfig(mode="zonal"), n_cells=DEM_SIDE, channel_mask=channel_pixels()
    )

    assert np.asarray(ctx.solver_mesh.top).reshape(DEM_SIDE, DEM_SIDE) == pytest.approx(dem)


def test_min_thickness_under_channel():
    dem = hill_dem()
    dem[4, 7] = 50.0  # thalweg far below the rest of its block
    bottom = 49.95  # only 5 cm under the thalweg pixel

    ctx = zonal_discretization(
        dem,
        TopSamplingConfig(mode="zonal", min_thickness_m=0.1),
        channel_mask=channel_pixels(),
        bottom=bottom,
    )

    assert block_tops(ctx)[1, 2] == pytest.approx(bottom + 0.1)


def test_inactive_cells_keep_fallback():
    size = PIXEL_M * DEM_SIDE
    labels = regular_grid_cell_ids(
        dem_transform=from_bounds(0.0, 0.0, size, size, DEM_SIDE, DEM_SIDE),
        dem_shape=(DEM_SIDE, DEM_SIDE),
        grid_bounds=(0.0, size, 0.0, size),
        grid_shape=(4, 4),
    )
    active = np.ones(16, dtype=bool)
    active[5] = False

    result = zonal_top(
        labels=labels,
        active=active,
        dem=np.full((DEM_SIDE, DEM_SIDE), 10.0),
        transform=None,
        out_shape=(DEM_SIDE, DEM_SIDE),
        centroid_top=np.full(16, 11.0),
        bottom=np.full(16, 10.5),
        spike_guard_tol_m=0.0,
    )

    assert result.top[5] == 11.0
    assert result.top[4] == pytest.approx(10.6)  # live cell, clamped to bottom + 0.1
    assert result.info["n_cells"] == 15.0
    assert result.info["n_thickness_clamped"] == 15.0


def test_finer_grid_skips_zonal(caplog):
    dem = hill_dem()
    dem[4, 7] -= 4.0
    with caplog.at_level(logging.INFO):
        zonal = zonal_discretization(
            dem,
            TopSamplingConfig(mode="zonal", min_pixels=1),
            n_cells=2 * DEM_SIDE,
            channel_mask=channel_pixels(),
        )
    plain = zonal_discretization(dem, TopSamplingConfig(), n_cells=2 * DEM_SIDE)

    np.testing.assert_array_equal(plain.solver_mesh.top, zonal.solver_mesh.top)
    assert any("Zonal top sampling skipped" in r.getMessage() for r in caplog.records)
