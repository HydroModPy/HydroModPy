"""A lake cutoff wall lies on the lake shore, with no cell between the reservoir and it.

The reservoir of ``tests/_helpers/reservoir_dam.py`` is meshed by the three
engines through the real planner, around the wall laid on its shore, which the
planner adds to the barrier family as the mesh step does. The LAK seal and the
HFB rows then close the same faces, which the gate checks.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest
import shapely
from shapely.geometry import LineString, Point

from hydromodpy.core.exceptions import SolverInputError
from hydromodpy.mesh import registry
from hydromodpy.mesh.mesh_config import MeshConfig
from hydromodpy.mesh.planning.lake_structures import LakeStructure
from hydromodpy.mesh.planning.plan import plan_mesh_request
from hydromodpy.model.boundaries.boundary_condition_registry import BoundaryConditionBundle
from hydromodpy.model.boundaries.cutoff_wall_shore import snap_wall_to_shore
from hydromodpy.model.sinks_sources.flow_barrier import CutoffWallConfig
from hydromodpy.solver.modflow6.builders._lake_geometry import downstream_of_wall, lake_shore_faces
from hydromodpy.solver.modflow6.builders.flow_barrier import (
    check_cutoff_wall_seal,
    resolve_flow_barrier_hfb_rows,
)
from hydromodpy.solver.modflow6.builders.lake import build_lake_connectiondata, cutoff_wall_pairs
from hydromodpy.solver.modflow6.builders.lake_cells import (
    apply_lake_idomain_mask,
    resolve_lake_cells_for_active_lakes,
)
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh
from tests._helpers.mesh_cases import LAMBERT93_WKT, grid_over, planning_inputs
from tests._helpers.model_factory import make_model
from tests._helpers.reservoir_dam import DOMAIN, reservoir, trace

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


def _built(engine: str, offset: float, *, snapped: bool = True) -> SimpleNamespace:
    """Mesh, lake cells, LAK rows and HFB rows of the reservoir with its wall."""
    declared = trace(offset)
    wall = snap_wall_to_shore(reservoir(), declared, 50.0)
    line = wall.line if snapped else declared
    shore = wall.shore if snapped else LineString()
    inputs = planning_inputs(
        grid_over(DOMAIN, 10.0, crs_wkt=LAMBERT93_WKT),
        domain=DOMAIN,
        watershed=DOMAIN,
        lakes=(wall.polygon,),
        lake_structures=(LakeStructure("voile", "r", line, 15.0, 60.0),),
        synthetic=False,
        barriers=(line,),
    )
    request = plan_mesh_request(MeshConfig.model_validate(ENGINES[engine]), inputs)
    cell_mesh = registry.mesh_engines.create(engine).build(request)
    n_cells = cell_mesh.n_cells
    solver_mesh = SolverMesh(
        cell_mesh=cell_mesh,
        top=np.full(n_cells, 10.0),
        botm=np.stack([np.full(n_cells, 5.0), np.zeros(n_cells)]),
        idomain=np.ones((2, n_cells), dtype=int),
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
        inputs=make_model(
            boundaries=BoundaryConditionBundle(conditions={}, active_ids=("lake",)),
            lakes={"r": payload},
        )
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


@pytest.mark.parametrize("engine", ["triangle", "voronoi"])
def test_cells_between_are_counted_only_with_a_shore(engine: str) -> None:
    built = _built(engine, 12.0, snapped=False)
    args = (built.model, built.mesh, built.cells_by_lake, built.connections, built.hfb)

    # The wall stays 12 m off the shore. Without a declared shore nothing is measured.
    check_cutoff_wall_seal(*args)
    built.model.inputs.lakes["r"]["cutoff_wall_shore"] = built.wall.shore

    with pytest.raises(SolverInputError, match=r"[1-9]\d* cell\(s\) between the lake and the wall"):
        check_cutoff_wall_seal(*args)


def test_a_lake_without_cells_is_not_checked() -> None:
    built = _built("triangle", 12.0)
    open_banks = build_lake_connectiondata(
        None, lake_index=0, lake_cell_ids=built.cells, bedleak=1e-6, solver_mesh=built.mesh
    )

    with pytest.raises(SolverInputError, match="still in LAK bank connection"):
        check_cutoff_wall_seal(built.model, built.mesh, built.cells_by_lake, open_banks, built.hfb)
    check_cutoff_wall_seal(built.model, built.mesh, {}, open_banks, built.hfb)
