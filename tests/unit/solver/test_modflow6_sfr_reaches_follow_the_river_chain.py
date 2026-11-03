"""On a mesh that carries the river chains, a reach is shared among the chain cells along it.

Each engine meshes the same river network as a ``rivers`` cell family: the thin
crossing chain of a regular grid, the left-bank triangles of a triangulation,
the generator cells of the Voronoi dual. The SFR builder shares each delineated
reach among the chain cells nearest to it, cut halfway between the projections
of consecutive centers, so the length of every reach is conserved and every
sub-reach sits on a chain cell, in order along the reach.
"""

from __future__ import annotations

from importlib.util import find_spec
from types import SimpleNamespace

import numpy as np
import pytest
from shapely.geometry import LineString

from hydromodpy.solver.modflow6.builders._sfr_network import chain_pieces
from hydromodpy.solver.modflow6.builders.sfr import resolve_sfr_networks
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh
from hydromodpy.spatial.geographic.core.sfr_network import SfrReachRow, SfrReachTrace
from hydromodpy.spatial.mesh import registry
from hydromodpy.spatial.mesh.model.planar_cell_mesh import PlanarCellMesh
from hydromodpy.spatial.mesh.request import LineFamilySpec
from tests._helpers.mesh_cases import L93_ORIGIN, LAMBERT93_WKT, grid_spec, mesh_request

X0, Y0 = L93_ORIGIN
_LENGTH_RTOL = 1e-9
_ENGINES = (
    "regular",
    pytest.param(
        "triangle",
        marks=pytest.mark.skipif(find_spec("gmsh") is None, reason="gmsh is not installed"),
    ),
    pytest.param(
        "voronoi",
        marks=pytest.mark.skipif(find_spec("gmsh") is None, reason="gmsh is not installed"),
    ),
)


def _p(x: float, y: float) -> tuple[float, float]:
    return (X0 + x, Y0 + y)


WEST = LineString([_p(120, 880), _p(260, 740), _p(350, 670), _p(500, 500)])
EAST = LineString([_p(880, 820), _p(720, 700), _p(590, 620), _p(500, 500)])
STUB = LineString([_p(500, 500), _p(512, 486)])
MAIN = LineString([_p(512, 486), _p(540, 380), _p(650, 250), _p(780, 70)])
REACHES = (
    (WEST, (), (2,)),
    (EAST, (), (2,)),
    (STUB, (0, 1), (3,)),
    (MAIN, (2,), ()),
)


def _cell_mesh(engine: str) -> PlanarCellMesh:
    river = LineString([*WEST.coords, *STUB.coords[1:], *MAIN.coords[1:]])
    return registry.create(engine).build(
        mesh_request(
            grid_spec(40, 40, 25.0, xmin=X0, ymin=Y0, crs_wkt=LAMBERT93_WKT),
            nominal_size_m=50.0,
            lines=(LineFamilySpec("rivers", "cell", (river, EAST)),),
        )
    )


def _model() -> SimpleNamespace:
    rows = tuple(
        SfrReachRow(
            ifno=ifno,
            line=line,
            rlen=float(line.length),
            rtp=90.0,
            rgrd=1e-3,
            strahler=1,
            area_km2=1.0,
            upstream=upstream,
            downstream=downstream,
            is_terminal_to_lake=False,
        )
        for ifno, (line, upstream, downstream) in enumerate(REACHES)
    )
    payload = {
        "width": {"kind": "constant", "value": 2.0},
        "reach_trace": SfrReachTrace(reaches=rows, crs_wkt=LAMBERT93_WKT),
    }
    return SimpleNamespace(
        flow=SimpleNamespace(active_bc=["sfr"], sinks_sources={"sfr": {"net": payload}})
    )


def _chain_cells(cell_mesh: PlanarCellMesh) -> set[int]:
    return {int(c) for chain in cell_mesh.chains("rivers") for c in chain.cell_ids}


@pytest.mark.parametrize("engine", _ENGINES)
def test_each_reach_keeps_its_length_on_the_chain_cells(engine: str) -> None:
    cell_mesh = _cell_mesh(engine)
    lines = [line for line, _, _ in REACHES]
    pieces = chain_pieces(cell_mesh, lines, family="rivers")
    chain = _chain_cells(cell_mesh)
    for line, shares in zip(lines, pieces, strict=True):
        assert shares, "every reach, the stub included, holds at least one cell"
        assert sum(s.length for s in shares) == pytest.approx(line.length, rel=_LENGTH_RTOL)
        assert {s.cell for s in shares} <= chain
        middles = [s.middle for s in shares]
        assert middles == sorted(middles)
        assert all(s.length > 0.0 for s in shares)


@pytest.mark.parametrize("engine", _ENGINES)
def test_the_network_routes_downstream_on_chain_cells(engine: str) -> None:
    cell_mesh = _cell_mesh(engine)
    n_cells = cell_mesh.n_cells
    solver_mesh = SolverMesh(
        cell_mesh=cell_mesh,
        top=np.full(n_cells, 100.0),
        botm=np.full((1, n_cells), 50.0),
        idomain=np.ones((1, n_cells), dtype=int),
    )
    network = resolve_sfr_networks(_model(), solver_mesh=solver_mesh)["net"]
    assert network.downstream_increasing
    assert {r.cellid[1] for r in network.reaches} <= _chain_cells(cell_mesh)
    total = sum(r.rlen for r in network.reaches)
    assert total == pytest.approx(sum(line.length for line, _, _ in REACHES), rel=_LENGTH_RTOL)
    outlets = [r for r in network.reaches if not r.downstream]
    assert len(outlets) == 1
