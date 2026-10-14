"""The generated Voronoi mesh: constraint seeds, free seeds, Lloyd, tessellation, gates.

Every step works in the local frame of the domain (``frame.py``). The cell of
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

from hydromodpy.spatial.mesh.engines.voronoi.constraints import ConstraintPlan, place_constraints
from hydromodpy.spatial.mesh.engines.voronoi.frame import LocalFrame, SizeSampler, local_frame
from hydromodpy.spatial.mesh.engines.voronoi.free_seeds import (
    free_seed_count,
    morton_order,
    sample_free_seeds,
)
from hydromodpy.spatial.mesh.engines.voronoi.gates import check_gates, gated_geometry
from hydromodpy.spatial.mesh.engines.voronoi.line_families import (
    cell_chains,
    cell_zones,
    face_family_table,
)
from hydromodpy.spatial.mesh.engines.voronoi.lloyd import LLOYD_TOLERANCE, lloyd_invariants, relax
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

__all__ = ["INWARD_M", "generate_cell_mesh", "with_family_stats"]

INWARD_M = 1.0e-7
"""A seed this close to the ring of its cell [m] is moved this far inside it.

A boundary seed lies on the ring of its clipped cell up to rounding, on the wrong
side of it in a part of the cases. The port wants every centre inside its cell.
"""


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
    balls, faces = plan.berge_balls(), plan.mirror_faces()
    chain_start, chain_end = plan.chain_segments()
    invariants = lloyd_invariants(
        berge_center=balls.center,
        berge_radius=balls.radius,
        chain_start=chain_start,
        chain_end=chain_end,
        constraint_xy=plan.seeds.xy,
        constraint_size=plan.seeds.radius,
    )
    report = relax(
        np.vstack([plan.seeds.xy, free]),
        n_constraint,
        h,
        domain,
        invariants,
        tolerance=float(request.options.get("lloyd_tolerance", LLOYD_TOLERANCE)),
    )
    tess = tessellate(report.seeds, n_constraint, domain, voronoi_envelope(domain, h.h_max))
    topology = cell_topology(tess.cells, frame)
    blocks = (CellBlock(cell_type=CellType.POLYGON, connectivity=topology.rings),)
    local_geometry = gated_geometry(HydroMesh(vertices=topology.vertices, cell_blocks=blocks))
    chains = cell_chains(plan)
    gates = check_gates(
        seeds=tess.seeds,
        cells=tess.cells,
        vertices=topology.vertices,
        geometry=local_geometry,
        domain_area=domain.area,
        frame=frame,
        chains=chains,
        balls=balls,
        faces=faces,
    )
    table = face_family_table(plan, local_geometry, topology.vertices)
    seeds = _inside_their_cells(tess.seeds, tess.cells)
    centers = frame.to_world(seeds)
    cell_mesh = build_planar_cell_mesh(
        HydroMesh(
            vertices=frame.to_world(topology.vertices),
            cell_blocks=blocks,
            cell_data={"disv_cell_center": centers},
        ),
        centers,
        center_kind="generator",
        crs_wkt=request.crs_wkt,
        identity=identity,
        declarations=declarations,
        cell_chains=chains,
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
    return with_family_stats(cell_mesh, plan.family_stats)


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
    merged = dataclasses.replace(cell_mesh, qa=dataclasses.replace(cell_mesh.qa, families=families))
    object.__setattr__(merged, "geometry", cell_mesh.geometry)
    return merged
