"""The generated Voronoi mesh: constraint seeds, free seeds, Lloyd, tessellation, gates.

Every step works in the local frame of the domain (``local_coords.py``). The cell of
seed ``i`` is cell ``i``, the constraint seeds first. The mesh is built twice on
the same vertices: once in the local frame, where the gates and the families
read it with the coordinates of the plan, and once in the world frame, which the
cell mesh keeps.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping, Sequence

import numpy as np
import shapely
from shapely.geometry import LineString

from hydromodpy.spatial.mesh.engines.voronoi.checks import check_gates, gated_geometry
from hydromodpy.spatial.mesh.engines.voronoi.constraints.plan import (
    ConstraintPlan,
    place_constraints,
)
from hydromodpy.spatial.mesh.engines.voronoi.families import cell_zones, face_family_table
from hydromodpy.spatial.mesh.engines.voronoi.free_seeds import (
    free_seed_count,
    morton_order,
    sample_free_seeds,
)
from hydromodpy.spatial.mesh.engines.voronoi.lloyd import LLOYD_TOLERANCE, constraint_disks, relax
from hydromodpy.spatial.mesh.engines.voronoi.local_coords import (
    LocalFrame,
    SizeSampler,
    local_frame,
)
from hydromodpy.spatial.mesh.engines.voronoi.tessellation import (
    cell_topology,
    tessellate,
    voronoi_envelope,
)
from hydromodpy.spatial.mesh.model.cell_types import CellType
from hydromodpy.spatial.mesh.model.hydro_mesh import CellBlock, HydroMesh
from hydromodpy.spatial.mesh.model.planar_cell_mesh import (
    MeshIdentity,
    PlanarCellMesh,
    build_planar_cell_mesh,
)
from hydromodpy.spatial.mesh.request import MeshRequest

__all__ = ["CLOSED_SHORE_SHARE", "INWARD_M", "generate_cell_mesh", "with_family_stats"]

INWARD_M = 1.0e-7
"""A seed this close to the ring of its cell [m] is moved this far inside it.

A boundary seed lies on the ring of its clipped cell up to rounding, on the wrong
side of it in a part of the cases. The port wants every centre inside its cell.
"""


CLOSED_SHORE_SHARE = 1.0 - 1.0e-6
"""Share of the lake shore the ``lakes`` faces must cover to enclose the lake regions."""


def generate_cell_mesh(
    request: MeshRequest,
    *,
    identity: MeshIdentity,
    declarations: Mapping[str, bool],
    notes: Sequence[str],
) -> PlanarCellMesh:
    """Place the seeds of *request*, relax them and tessellate; the gates raise on any fault.

    *request* carries a size field. *notes* open the notes of the mesh QA.
    """
    frame = local_frame(request.domain)
    h = SizeSampler.of_request(request, frame)
    plan = place_constraints(request, frame, h)
    domain = shapely.normalize(frame.to_local(request.domain))
    shapely.prepare(domain)
    n_constraint = plan.seeds.n
    rng = np.random.Generator(np.random.PCG64(request.seed))
    free = sample_free_seeds(
        rng,
        h,
        domain,
        plan.seeds.xy,
        plan.seeds.radius,
        free_seed_count(h, domain, n_constraint),
    )
    free = free[morton_order(free)]
    report = relax(
        np.vstack([plan.seeds.xy, free]),
        n_constraint,
        h,
        domain,
        *constraint_disks(plan),
        tolerance=float(request.options.get("lloyd_tolerance", LLOYD_TOLERANCE)),
    )
    tess = tessellate(report.seeds, n_constraint, domain, voronoi_envelope(domain, h.h_max))
    topology = cell_topology(tess.cells, frame)
    blocks = (CellBlock(cell_type=CellType.POLYGON, connectivity=topology.rings),)
    local_geometry = gated_geometry(HydroMesh(vertices=topology.vertices, cell_blocks=blocks))
    gates = check_gates(
        seeds=tess.seeds,
        cells=tess.cells,
        vertices=topology.vertices,
        geometry=local_geometry,
        domain_area=domain.area,
        frame=frame,
        chains=plan.chains,
        plan=plan,
    )
    table = face_family_table(plan, local_geometry, topology.vertices)
    seeds = _inside_their_cells(tess.seeds, tess.cells)
    centers = frame.to_world(seeds)
    cell_mesh = build_planar_cell_mesh(
        HydroMesh(vertices=frame.to_world(topology.vertices), cell_blocks=blocks),
        centers,
        center_kind="generator",
        crs_wkt=request.crs_wkt,
        identity=identity,
        declarations=declarations,
        cell_chains=plan.chains,
        face_families=table,
        cell_zone=cell_zones(plan, local_geometry, topology.vertices, table),
        zone_names=plan.zone_names,
        domain_area_m2=request.domain.area,
        lines=_world_lines(plan, frame),
        target_size=h(seeds),
        notes=(*notes, *plan.notes),
        extras={
            **plan.seed_extras(),
            **report.extras(),
            **gates.extras(),
            "n_seeds_free": float(len(free)),
            "boundary_seeds_added": float(tess.boundary_seeds_added),
            "origin_x": frame.origin[0],
            "origin_y": frame.origin[1],
        },
    )
    return _with_open_shore_note(with_family_stats(cell_mesh, plan.family_stats))


def _with_open_shore_note(cell_mesh: PlanarCellMesh) -> PlanarCellMesh:
    """The cell mesh, with a note when its ``lakes`` faces leave part of a shore open.

    The lake builder then takes every cell a lake overlaps, with that overlap:
    the note says so where the mesh is built, not where the lake is.
    """
    lakes = cell_mesh.qa.families.get("lakes")
    if not lakes or "covered_length_rel" not in lakes:
        return cell_mesh
    covered = float(lakes["covered_length_rel"])
    if covered >= CLOSED_SHORE_SHARE:
        return cell_mesh
    note = (
        f"lakes: the faces follow {100.0 * covered:.1f} % of the shore; where two stretches "
        "of shore, a river or a barrier come closer than about a cell the mirror pairs "
        "yield, the lake regions stay open and each lake takes the cells it overlaps. "
        "Refine the lake shore ([mesh.lake_refinement] cell_size) to close it"
    )
    return cell_mesh.with_qa(dataclasses.replace(cell_mesh.qa, notes=(*cell_mesh.qa.notes, note)))


def _inside_their_cells(seeds: np.ndarray, cells: np.ndarray) -> np.ndarray:
    """The seeds, those within :data:`INWARD_M` of the ring of their cell moved inside it."""
    on_ring = shapely.dwithin(shapely.get_exterior_ring(cells), shapely.points(seeds), INWARD_M)
    if not on_ring.any():
        return seeds
    inward = shapely.get_coordinates(shapely.centroid(cells[on_ring])) - seeds[on_ring]
    moved = np.array(seeds, copy=True)
    moved[on_ring] += INWARD_M * inward / np.hypot(*inward.T)[:, None]
    return moved


def _world_lines(plan: ConstraintPlan, frame: LocalFrame) -> dict[str, tuple[LineString, ...]]:
    """The source lines of each family, in the world frame, for the QA."""
    return {
        name: tuple(frame.to_world(line) for line in lines)
        for name, lines in plan.source_lines.items()
    }


def with_family_stats(
    cell_mesh: PlanarCellMesh, stats: Mapping[str, Mapping[str, float]]
) -> PlanarCellMesh:
    """The cell mesh with the family numbers of the engine added to its QA families."""
    families = {name: dict(numbers) for name, numbers in cell_mesh.qa.families.items()}
    for name, numbers in stats.items():
        families.setdefault(name, {}).update(numbers)
    return cell_mesh.with_qa(dataclasses.replace(cell_mesh.qa, families=families))
