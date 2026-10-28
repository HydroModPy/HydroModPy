"""The ``regular`` engine hands the solvers the grid the flopy round trip handed them.

Before the unified mesh, a regular grid went surfaces -> ``StructuredGridBuilder``
-> flopy ``StructuredGrid`` -> a ``SolverMesh``. Now the planar grid is
the one of the engine and the surfaces give the vertical part only. The input
files of MODFLOW-NWT (DIS) and MODFLOW 6 (DISV) must not move by one bit.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import flopy
import numpy as np
import pytest
from flopy.discretization import StructuredGrid

from hydromodpy.solver.modflow_grid import SolverMesh, build_spatial_discretization
from hydromodpy.solver.modflow_grid.discretization_spatial import StructuredGridBuilder
from hydromodpy.solver.modflow_grid.sgrid_config import SolverSGridConfig
from hydromodpy.spatial import RasterSupport, Surface
from hydromodpy.spatial.domain.domain import Domain
from hydromodpy.spatial.domain.domain_config import DomainConfig
from hydromodpy.spatial.domain.layers_config import VerticalGridConfig
from hydromodpy.spatial.mesh import registry
from hydromodpy.spatial.mesh.request import RasterGridSpec
from tests._helpers.cell_meshes import TEST_CRS_WKT
from tests._helpers.mesh_cases import mesh_request
from tests._helpers.solver_meshes import solver_mesh_from_sgrid

_NODATA = -9999.0


@dataclass(frozen=True)
class _Case:
    nrow: int
    ncol: int
    xmin: float
    ymin: float
    dx: float
    dy: float
    shape: tuple[int, int] | None = None
    """Shape of the mesh when it differs from the one of the DEM."""


_CASES = {
    "native_75m": _Case(nrow=6, ncol=8, xmin=372_337.5, ymin=6_788_912.5, dx=75.0, dy=75.0),
    "non_integer_step": _Case(nrow=7, ncol=5, xmin=1234.567, ymin=7654.321, dx=12.3, dy=12.3),
    "negative_origin": _Case(nrow=5, ncol=9, xmin=-1500.25, ymin=-830.5, dx=3.3, dy=3.3),
    "band_1_by_40": _Case(nrow=1, ncol=40, xmin=0.0, ymin=0.0, dx=25.0, dy=25.0),
    "coarser_than_the_dem": _Case(
        nrow=12, ncol=12, xmin=100.0, ymin=-40.0, dx=25.0, dy=25.0, shape=(4, 3)
    ),
}


def _surface(case: _Case, values: np.ndarray, name: str) -> Surface:
    support = RasterSupport(
        crs="EPSG:2154",
        dx=case.dx,
        dy=case.dy,
        xmin=case.xmin,
        xmax=case.xmin + case.dx * case.ncol,
        ymin=case.ymin,
        ymax=case.ymin + case.dy * case.nrow,
        nrows=case.nrow,
        ncols=case.ncol,
        nodata=_NODATA,
    )
    return Surface(name=name, values=values, support=support)


def _domain(case: _Case) -> Domain:
    rng = np.random.default_rng(11)
    top = 50.0 + rng.uniform(0.0, 20.0, size=(case.nrow, case.ncol))
    if case.nrow * case.ncol > 4:
        top[0, 0] = _NODATA
    domain = Domain(config=DomainConfig(), surface_topo=_surface(case, top, "surface_topo"))
    domain.substratum = _surface(case, np.full(top.shape, 10.0), "substratum")
    return domain


def _engine_mesh(case: _Case, domain: Domain):
    support = domain.surface_topo.support
    grid = RasterGridSpec.from_raster_support(support, crs_wkt=TEST_CRS_WKT)
    options = {} if case.shape is None else {"shape": list(case.shape)}
    request = mesh_request(grid, nominal_size_m=case.dx, options=options)
    return registry.create("regular").build(request)


def _legacy_solver_mesh(case: _Case, domain: Domain, vertical: VerticalGridConfig) -> SolverMesh:
    """The solver mesh of the flopy round trip, as the code built it before."""
    top_surface, bottom_surface = domain.surface_topo, domain.substratum
    if case.shape is not None:
        top_surface = top_surface.resample_to_shape(
            *case.shape, resampling="bilinear", nodata=_NODATA, name=top_surface.name
        )
        bottom_surface = bottom_surface.resample_to_shape(
            *case.shape, resampling="bilinear", nodata=_NODATA, name=bottom_surface.name
        )
    top = np.asarray(top_surface.as_array(), dtype=float)
    bottom = np.asarray(bottom_surface.as_array(), dtype=float)
    spec = StructuredGridBuilder().build_from_surfaces(
        top_surface=top_surface, bottom_surface=bottom_surface, vertical_config=vertical
    )
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
    inactive = ~np.isfinite(top) | ~np.isfinite(bottom) | (top <= _NODATA) | (bottom <= _NODATA)
    return solver_mesh_from_sgrid(
        sgrid, zbot=np.asarray(sgrid.botm, dtype=float), inactive_mask=inactive
    )


def _write_dis(solver_mesh: SolverMesh, folder: Path) -> str:
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


def _write_disv(solver_mesh: SolverMesh, folder: Path) -> str:
    """Write the MODFLOW 6 DISV file of a solver mesh and read it back, without its time stamp."""
    sim = flopy.mf6.MFSimulation(sim_name="disv", sim_ws=str(folder), exe_name="mf6")
    flopy.mf6.ModflowTdis(sim, nper=1, perioddata=[(1.0, 1, 1.0)])
    gwf = flopy.mf6.ModflowGwf(sim, modelname="disv")
    flopy.mf6.ModflowGwfdisv(gwf, length_units="METERS", **solver_mesh.to_disv_kwargs())
    sim.write_simulation(silent=True)
    lines = (folder / "disv.disv").read_text().splitlines(keepends=True)
    return "".join(line for line in lines if not line.startswith("# File generated by Flopy"))


@pytest.mark.parametrize("case_name", sorted(_CASES))
def test_the_dis_and_the_disv_of_a_regular_grid_do_not_move(case_name: str, tmp_path: Path) -> None:
    case = _CASES[case_name]
    domain = _domain(case)
    vertical = VerticalGridConfig(genmtd_lay="constant", nlay=2, nodata=_NODATA)
    legacy = _legacy_solver_mesh(case, domain, vertical)

    ctx = build_spatial_discretization(
        domain=domain,
        vertical_config=vertical,
        sgrid_config=SolverSGridConfig(),
        cell_mesh=_engine_mesh(case, domain),
    )
    now = ctx.solver_mesh

    assert now.is_structured
    assert now.structured_shape == legacy.structured_shape
    assert np.array_equal(now.planar_mesh.vertices, legacy.planar_mesh.vertices)
    assert np.array_equal(now.planar_mesh.flat_connectivity, legacy.planar_mesh.flat_connectivity)
    assert np.array_equal(now.top, legacy.top)
    assert np.array_equal(now.botm, legacy.botm)
    assert np.array_equal(now.inactive_mask, legacy.inactive_mask)
    assert _write_dis(now, tmp_path / "now_dis") == _write_dis(legacy, tmp_path / "legacy_dis")
    assert _write_disv(now, tmp_path / "now_disv") == _write_disv(legacy, tmp_path / "legacy_disv")
