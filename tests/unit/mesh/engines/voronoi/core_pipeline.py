"""A small Voronoi pipeline over the numerical core, without constraints or families.

Boundary seeds at the local size along the domain rings (corners fixed),
free seeds, Lloyd, final tessellation, shared vertices and the gates: what the
engine does once its constraint seeds are placed.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import shapely
from shapely.geometry import LineString, Polygon

from hydromodpy.spatial.mesh.engines.voronoi.frame import LocalFrame, SizeSampler, local_frame
from hydromodpy.spatial.mesh.engines.voronoi.free_seeds import (
    free_seed_count,
    morton_order,
    sample_free_seeds,
)
from hydromodpy.spatial.mesh.engines.voronoi.gates import (
    BergeBalls,
    GateReport,
    MirrorFaces,
    check_gates,
    gated_geometry,
)
from hydromodpy.spatial.mesh.engines.voronoi.lloyd import LloydReport, lloyd_invariants, relax
from hydromodpy.spatial.mesh.engines.voronoi.tessellation import (
    CellTopology,
    Tessellation,
    cell_topology,
    tessellate,
    voronoi_envelope,
)
from hydromodpy.spatial.mesh.model.cell_types import CellType
from hydromodpy.spatial.mesh.model.derived_geometry import DerivedGeometry
from hydromodpy.spatial.mesh.model.hydro_mesh import CellBlock, HydroMesh
from hydromodpy.spatial.mesh.planning.resample import positions_at_local_size
from hydromodpy.spatial.mesh.request import RasterGridSpec, SizeField

WKT = 'PROJCS["RGF93 / Lambert-93"]'
X0, Y0 = 350_000.0, 6_800_000.0


def size_field(domain: Polygon, pixel: float, size: np.ndarray | float) -> SizeField:
    """A field over the domain bounding box: a constant, or ``size(x_local_share)``."""
    xmin, ymin, xmax, ymax = domain.bounds
    ncol = math.ceil((xmax - xmin) / pixel)
    nrow = math.ceil((ymax - ymin) / pixel)
    grid = RasterGridSpec(
        xmin=xmin,
        xmax=xmin + ncol * pixel,
        ymin=ymax - nrow * pixel,
        ymax=ymax,
        dx=pixel,
        dy=pixel,
        nrow=nrow,
        ncol=ncol,
        crs_wkt=WKT,
    )
    values = np.broadcast_to(np.asarray(size, dtype=float), (nrow, ncol)).copy()
    return SizeField(values=values, grid=grid)


def ring_seeds(domain: Polygon, h: SizeSampler) -> np.ndarray:
    """Seeds on every ring of the local domain: its vertices, then points at the local size."""
    points = []
    for ring in [domain.exterior, *domain.interiors]:
        corners = np.asarray(ring.coords)[:-1]
        for a, b in zip(corners, np.roll(corners, -1, axis=0), strict=True):
            inner, _, _ = positions_at_local_size(LineString([a, b]), h.h_min / 4.0, h, ring=False)
            points += [a, *inner]
    return np.asarray(points, dtype=float)


@dataclass(frozen=True, eq=False)
class CoreMesh:
    """Everything the core produced, local and world."""

    frame: LocalFrame
    h: SizeSampler
    domain: Polygon
    lloyd: LloydReport
    tessellation: Tessellation
    topology: CellTopology
    mesh: HydroMesh
    geometry: DerivedGeometry
    gates: GateReport


def core_mesh(
    world_domain: Polygon,
    field: SizeField,
    *,
    seed: int = 0,
    fixed: np.ndarray | None = None,
    balls: BergeBalls | None = None,
    faces: MirrorFaces | None = None,
    cap: int = 25,
) -> CoreMesh:
    """Mesh *world_domain*; *fixed* local constraint seeds go before the ring seeds."""
    frame = local_frame(world_domain)
    h = SizeSampler(field, frame)
    domain = frame.to_local(world_domain)
    shapely.prepare(domain)
    constraint = ring_seeds(domain, h)
    if fixed is not None:
        constraint = np.vstack([fixed, constraint])
    size = h(constraint)
    n_free = free_seed_count(h, domain, len(constraint))
    rng = np.random.Generator(np.random.PCG64(seed))
    free = sample_free_seeds(rng, h, domain, constraint, size, n_free)
    free = free[morton_order(free)]
    seeds = np.vstack([constraint, free])
    hard_center = np.empty((0, 2)) if balls is None else balls.center
    hard_radius = np.empty(0) if balls is None else balls.radius
    invariants = lloyd_invariants(
        berge_center=hard_center,
        berge_radius=hard_radius,
        chain_start=np.empty((0, 2)),
        chain_end=np.empty((0, 2)),
        constraint_xy=constraint,
        constraint_size=size,
    )
    lloyd = relax(seeds, len(constraint), h, domain, invariants, cap=cap)
    tess = tessellate(lloyd.seeds, len(constraint), domain, voronoi_envelope(domain, h.h_max))
    topology = cell_topology(tess.cells, frame)
    mesh = HydroMesh(
        vertices=frame.to_world(topology.vertices),
        cell_blocks=(CellBlock(CellType.POLYGON, topology.rings),),
    )
    geometry = gated_geometry(mesh)
    report = check_gates(
        seeds=tess.seeds,
        cells=tess.cells,
        vertices=topology.vertices,
        geometry=geometry,
        domain_area=domain.area,
        frame=frame,
        balls=balls,
        faces=faces,
    )
    return CoreMesh(frame, h, domain, lloyd, tess, topology, mesh, geometry, report)
