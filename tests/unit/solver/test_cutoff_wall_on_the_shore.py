"""A lake cutoff wall lies on the lake shore, with no cell between the reservoir and it.

The reservoir of ``tests/_helpers/reservoir_dam.py`` is meshed by the three
engines through the real planner, around the wall laid on its shore. The LAK
seal and the HFB rows then close the same faces, which the gate checks.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest
import shapely
from pyproj import CRS
from shapely.geometry import LineString, Point

from hydromodpy.core.exceptions import SolverInputError
from hydromodpy.physics.flow.cutoff_wall_shore import snap_wall_to_shore
from hydromodpy.physics.flow.sinks_sources import CutoffWallConfig
from hydromodpy.solver.modflow6.builders import (
    apply_lake_idomain_mask,
    build_lake_connectiondata,
    check_cutoff_wall_seal,
    resolve_flow_barrier_hfb_rows,
    resolve_lake_cells_for_active_lakes,
)
from hydromodpy.solver.modflow6.builders.lake import cutoff_wall_pairs
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh
from hydromodpy.spatial.mesh import registry
from hydromodpy.spatial.mesh.config.mesh import MeshConfig
from hydromodpy.spatial.mesh.ops.flow_barrier import downstream_of_wall, lake_shore_faces
from hydromodpy.spatial.mesh.planning.inputs import PlanningInputs
from hydromodpy.spatial.mesh.planning.plan import plan_mesh_request
from hydromodpy.spatial.mesh.request import RasterGridSpec
from tests._helpers.reservoir_dam import DOMAIN, reservoir, trace

WKT = CRS.from_epsg(2154).to_wkt()
ENGINES = {
    "regular": {"engine": "regular", "cell_size": 40.0},
    "triangle": {
        "engine": "triangle",
        "cell_size": 60.0,
        "lake_refinement": {"cell_size": 30.0, "dam_cell_size": 15.0, "dam_buffer": 60.0},
    },
    "voronoi": {
        "engine": "voronoi",
        "cell_size": 60.0,
        "lake_refinement": {"cell_size": 30.0, "dam_cell_size": 15.0, "dam_buffer": 60.0},
    },
}


def _grid() -> RasterGridSpec:
    xmin, ymin, xmax, ymax = DOMAIN.bounds
    return RasterGridSpec(
        xmin=xmin,
        xmax=xmax,
        ymin=ymin,
        ymax=ymax,
        dx=10.0,
        dy=10.0,
        nrow=round((ymax - ymin) / 10.0),
        ncol=round((xmax - xmin) / 10.0),
        crs_wkt=WKT,
    )


def _built(engine: str, offset: float, *, snapped: bool = True) -> SimpleNamespace:
    """Mesh, lake cells, LAK rows and HFB rows of the reservoir with its wall."""
    declared = trace(offset)
    wall = snap_wall_to_shore(reservoir(), declared, 50.0)
    line = wall.line if snapped else declared
    shore = wall.shore if snapped else LineString()
    inputs = PlanningInputs(
        dem_grid=_grid(),
        crs_wkt=WKT,
        domain=DOMAIN,
        river_trace=None,
        watershed=DOMAIN,
        lakes=(wall.polygon,),
        lake_structures=(("voile:r", line, 15.0, 60.0),),
        geology=None,
        refinement_zones=(),
        input_triangulation=None,
        synthetic=False,
    )
    request = plan_mesh_request(MeshConfig.model_validate(ENGINES[engine]), inputs)
    cell_mesh = registry.create(engine).build(request)
    n_cells = cell_mesh.n_cells
    solver_mesh = SolverMesh(
        cell_mesh=cell_mesh,
        top=np.full(n_cells, 10.0),
        botm=np.stack([np.full(n_cells, 5.0), np.zeros(n_cells)]),
        inactive_mask=np.zeros((2, n_cells), dtype=bool),
    )
    coords = [list(xy) for xy in declared.coords]
    payload = {
        "polygon": wall.polygon,
        "cutoff_wall": CutoffWallConfig(line=coords, depths=[8.0], hydchr=1e-9),
        "cutoff_wall_trace": declared,
        "cutoff_wall_line": line,
        "cutoff_wall_shore": shore,
    }
    model = SimpleNamespace(
        flow=SimpleNamespace(active_bc=["lake"], sinks_sources={"lakes": {"r": payload}})
    )
    cells = resolve_lake_cells_for_active_lakes(model, solver_mesh)
    masked = apply_lake_idomain_mask(solver_mesh, lake_cell_ids_by_lake=cells)
    connections = build_lake_connectiondata(
        None,
        lake_index=0,
        lake_cell_ids=cells["r"],
        bedleak=1e-6,
        solver_mesh=masked,
        sealed_faces=cutoff_wall_pairs(payload, cells["r"], masked),
    )
    hfb = resolve_flow_barrier_hfb_rows(model, masked, cells)
    return SimpleNamespace(
        model=model,
        mesh=masked,
        wall=wall,
        line=line,
        cells=np.asarray(cells["r"]),
        cells_by_lake=cells,
        connections=connections,
        hfb=hfb,
    )


def _section_faces(built: SimpleNamespace) -> np.ndarray:
    """The HFB faces ``(a, b)`` along the shore section, one cell size from its ends.

    At a corner of the shore the cells round the corner, and the faces that
    close the fence there join bank cells: they belong to the corner, not to
    the section.
    """
    shore = built.wall.shore
    first = built.line.project(Point(shore.coords[0]))
    last = built.line.project(Point(shore.coords[-1]))
    pairs = np.unique([sorted((row[0][1], row[1][1])) for row in built.hfb], axis=0)
    geometry = built.mesh.cell_mesh.geometry
    edge_of = {tuple(pair): k for k, pair in enumerate(geometry.edge_cells.tolist())}
    rows = np.array([edge_of[tuple(pair)] for pair in pairs.tolist()])
    along = shapely.line_locate_point(built.line, shapely.points(geometry.edge_midpoint[rows]))
    size = np.sqrt(geometry.areas[pairs]).max(axis=1)
    return pairs[(along > first + size) & (along < last - size)]


@pytest.mark.parametrize("offset", [12.0, -30.0], ids=["gap_12_m", "crossing"])
@pytest.mark.parametrize("engine", sorted(ENGINES))
def test_every_hfb_face_of_the_shore_touches_a_lake_cell(engine: str, offset: float) -> None:
    built = _built(engine, offset)
    faces = _section_faces(built)
    lake = np.isin(faces, built.cells)

    assert faces.size
    assert lake.any(axis=1).all()


@pytest.mark.parametrize("offset", [12.0, -30.0], ids=["gap_12_m", "crossing"])
@pytest.mark.parametrize("engine", sorted(ENGINES))
def test_no_cell_sits_between_the_lake_and_the_wall(engine: str, offset: float) -> None:
    built = _built(engine, offset)
    faces = _section_faces(built).reshape(-1)
    outside = faces[~np.isin(faces, built.cells)]
    between = ~downstream_of_wall(built.line, built.mesh.cell_mesh.centers[outside])

    assert np.count_nonzero(between) == 0
    assert not downstream_of_wall(built.line, built.mesh.cell_mesh.centers[built.cells]).any()


@pytest.mark.parametrize("engine", sorted(ENGINES))
def test_the_shore_is_sealed_in_the_lake_layer_and_barred_below_the_bed(engine: str) -> None:
    built = _built(engine, 12.0)
    cell_mesh = built.mesh.cell_mesh
    shore = cell_mesh.geometry.edge_cells[lake_shore_faces(cell_mesh, built.line, built.cells)]
    outer = shore[~np.isin(shore, built.cells)]
    banks = {row[2][1] for row in built.connections if row[3] == "HORIZONTAL"}
    barred = {(row[0][0], *sorted((row[0][1], row[1][1]))) for row in built.hfb}

    assert shore.size
    assert banks.isdisjoint(outer.tolist())
    assert all((1, a, b) in barred and (0, a, b) not in barred for a, b in shore.tolist())


@pytest.mark.parametrize("engine", sorted(ENGINES))
def test_the_gate_passes_the_wall_on_the_shore(engine: str) -> None:
    built = _built(engine, 12.0)
    check_cutoff_wall_seal(
        built.model, built.mesh, built.cells_by_lake, built.connections, built.hfb
    )


@pytest.mark.parametrize("engine", ["triangle", "voronoi"])
def test_the_trace_left_12_m_off_the_shore_leaves_cells_between(engine: str) -> None:
    built = _built(engine, 12.0, snapped=False)
    centres = built.mesh.cell_mesh.centers
    probe = built.wall.shore.buffer(12.0 - 1.0, cap_style="flat")
    strip = np.flatnonzero(shapely.contains(probe, shapely.points(centres)))
    strip = strip[
        ~np.isin(strip, built.cells) & ~built.wall.polygon.contains(shapely.points(centres[strip]))
    ]

    assert strip.size > 0
    assert not downstream_of_wall(built.line, centres[strip]).any()


@pytest.mark.parametrize("engine", sorted(ENGINES))
def test_the_gate_refuses_a_shore_face_left_without_its_hfb_row(engine: str) -> None:
    built = _built(engine, 12.0)
    cell_mesh = built.mesh.cell_mesh
    a, b = cell_mesh.geometry.edge_cells[lake_shore_faces(cell_mesh, built.line, built.cells)][0]
    rows = [row for row in built.hfb if sorted((row[0][1], row[1][1])) != [a, b]]

    with pytest.raises(SolverInputError, match=r"lake 'r'.*1 lake face\(s\) without"):
        check_cutoff_wall_seal(
            built.model, built.mesh, built.cells_by_lake, built.connections, rows
        )


def test_the_gate_refuses_a_lake_still_in_bank_connection_past_the_dam() -> None:
    built = _built("triangle", 12.0)
    open_banks = build_lake_connectiondata(
        None,
        lake_index=0,
        lake_cell_ids=built.cells,
        bedleak=1e-6,
        solver_mesh=built.mesh,
    )

    with pytest.raises(SolverInputError, match=r"lake 'r'.*downstream cell\(s\) still in LAK"):
        check_cutoff_wall_seal(built.model, built.mesh, built.cells_by_lake, open_banks, built.hfb)
