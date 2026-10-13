"""Turn ``[mesh]`` and the project inputs into one mesh request.

The planner fixes the intent of each line family, builds the size field of a
graded engine and resamples its lines at the local size. A non-graded engine
(``regular``) gets the raw lines and no size field. A triangulation read from
a file is meshed as it is: no size field, raw lines, its own outline as the
domain.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

import shapely
from shapely.geometry import LineString, Polygon
from shapely.geometry.base import BaseGeometry

from hydromodpy.spatial.mesh import registry
from hydromodpy.spatial.mesh.config.mesh import MeshConfig, MeshTriangleConfig, MeshVoronoiConfig
from hydromodpy.spatial.mesh.planning.input_mesh import domain_polygon_of
from hydromodpy.spatial.mesh.planning.inputs import PlanningInputs
from hydromodpy.spatial.mesh.planning.resample import resample_families
from hydromodpy.spatial.mesh.request import LineFamilySpec, MeshRequest, RasterGridSpec, SizeField
from hydromodpy.spatial.mesh.sizing.size_field import (
    OutsideCoarsening,
    SizeTerm,
    build_size_field,
)

__all__ = ["plan_mesh_request"]


def _pixel_size(grid: RasterGridSpec) -> float:
    """The DEM pixel size in metres: the larger step, so no cell is finer than a pixel."""
    return max(grid.dx, grid.dy)


def plan_mesh_request(mesh_cfg: MeshConfig, inputs: PlanningInputs) -> MeshRequest:
    """Return the request the engine of *mesh_cfg* meshes the project inputs with."""
    graded = registry.get(mesh_cfg.engine).capabilities.graded
    triangulation = inputs.input_triangulation
    domain = inputs.domain if triangulation is None else domain_polygon_of(triangulation)
    families = _families(mesh_cfg, inputs, domain)
    pixel = _pixel_size(inputs.dem_grid)
    size_field: SizeField | None = None
    notes = list(inputs.notes)
    if graded and triangulation is None:
        h0 = max(mesh_cfg.cell_size or pixel, pixel)
        size_field = build_size_field(
            inputs.dem_grid,
            h0=h0,
            h_floor=pixel,
            terms=_size_terms(mesh_cfg, inputs, families, h0=h0, pixel=pixel),
            outside=_outside(mesh_cfg, inputs),
            max_slope=mesh_cfg.max_slope,
        )
        resampled = resample_families(families, domain=domain, size_field=size_field)
        if resampled.short_fixed_edges:
            notes.append(
                f"{resampled.short_fixed_edges} line edges between fixed nodes are shorter "
                "than 0.8 local cell and were kept whole"
            )
        families = resampled.families
        nominal = h0
    else:
        nominal = mesh_cfg.cell_size or pixel
        notes.extend(_ignored_settings(mesh_cfg, graded=graded))
    return MeshRequest(
        domain=domain,
        crs_wkt=inputs.crs_wkt,
        grid=inputs.dem_grid,
        nominal_size_m=nominal,
        lines=families,
        size_field=size_field,
        seed=mesh_cfg.seed,
        options=_engine_options(mesh_cfg, inputs.dem_grid),
        input_triangulation=triangulation,
        notes=tuple(notes),
    )


def _ignored_settings(mesh_cfg: MeshConfig, *, graded: bool) -> list[str]:
    """Notes on the grading settings an ungraded engine does not follow."""
    if graded:
        return []
    ignored = [
        name for name in ("river_cell_size", "river_band") if getattr(mesh_cfg, name) is not None
    ]
    if not ignored:
        return []
    return [f"{mesh_cfg.engine} ignores {' and '.join(ignored)}: it does not grade its cells"]


def _families(
    mesh_cfg: MeshConfig, inputs: PlanningInputs, domain: Polygon
) -> tuple[LineFamilySpec, ...]:
    """The line families ``[mesh.families]`` asks for, clipped to *domain*."""
    wanted = mesh_cfg.families
    families: list[LineFamilySpec] = []
    if wanted.rivers == "cell" and inputs.river_trace is not None:
        lines, _ = _clipped(inputs.river_trace.lines, domain)
        if lines:
            families.append(LineFamilySpec("rivers", "cell", lines))
    if wanted.geology == "face" and inputs.geology is not None:
        lines, zones = _clipped(
            inputs.geology.lines,
            domain,
            zip(inputs.geology.zone_left, inputs.geology.zone_right, strict=True),
        )
        if lines:
            families.append(
                LineFamilySpec(
                    "geology",
                    "face",
                    lines,
                    zone_left=tuple(left for left, _ in zones),
                    zone_right=tuple(right for _, right in zones),
                )
            )
    if wanted.lakes == "face" and inputs.lakes:
        lines, _ = _clipped(_rings(inputs.lakes), domain)
        if lines:
            families.append(LineFamilySpec("lakes", "face", lines, closed=True))
    if wanted.watershed_boundary == "face" and inputs.watershed is not None:
        lines, _ = _clipped(_rings((inputs.watershed,)), domain)
        if lines:
            families.append(LineFamilySpec("watershed_boundary", "face", lines, closed=True))
    return tuple(families)


def _rings(polygons: Iterable[Polygon]) -> list[LineString]:
    """Every ring of *polygons* in normalized form, sorted, so their order never counts."""
    rings = []
    for polygon in polygons:
        normal = shapely.normalize(polygon)
        rings.append(LineString(normal.exterior.coords))
        rings.extend(LineString(ring.coords) for ring in normal.interiors)
    return sorted(rings, key=lambda ring: tuple(map(tuple, ring.coords)))


def _clipped(
    lines: Iterable[LineString],
    domain: Polygon,
    tags: Iterable[object] | None = None,
) -> tuple[tuple[LineString, ...], list[object]]:
    """The parts of *lines* inside *domain*, each oriented as its source, with its tag."""
    tag_list = list(tags) if tags is not None else None
    parts_out: list[LineString] = []
    tags_out: list[object] = []
    for index, line in enumerate(lines):
        pieces = []
        for part in shapely.get_parts(shapely.line_merge(line.intersection(domain))):
            if not isinstance(part, LineString) or part.length <= 0.0:
                continue
            if _runs_backwards(part, line):
                part = LineString(part.coords[::-1])
            pieces.append((line.project(shapely.Point(part.coords[0])), part))
        for _, part in sorted(pieces, key=lambda piece: piece[0]):
            parts_out.append(part)
            tags_out.append(tag_list[index] if tag_list is not None else None)
    return tuple(parts_out), tags_out


def _runs_backwards(part: LineString, source: LineString) -> bool:
    """Whether *part*, a piece of *source*, runs against it; a ring wraps at its start."""
    head = source.project(shapely.Point(part.coords[0]))
    ahead = source.project(part.interpolate(min(0.5 * part.length, 1.0e-3 * source.length)))
    advance = ahead - head
    if source.is_closed:
        advance %= source.length
        return advance > 0.5 * source.length
    return advance < 0.0


def _size_terms(
    mesh_cfg: MeshConfig,
    inputs: PlanningInputs,
    families: tuple[LineFamilySpec, ...],
    *,
    h0: float,
    pixel: float,
) -> list[SizeTerm]:
    """The refinement terms: rivers, lake shore, interior and structures, user zones."""
    terms: list[SizeTerm] = []
    rivers = next((family for family in families if family.name == "rivers"), None)
    if rivers is not None:
        terms.append(
            SizeTerm(
                name="rivers",
                region=shapely.multilinestrings(rivers.lines),
                size_m=max(mesh_cfg.river_cell_size or pixel, pixel),
                ramp_m=mesh_cfg.river_band if mesh_cfg.river_band is not None else 2.0 * h0,
            )
        )
    lake_cfg = mesh_cfg.lake_refinement
    if lake_cfg is not None:
        if inputs.lakes:
            lakes = shapely.union_all(inputs.lakes)
            band = lake_cfg.shoreline_band
            terms.append(
                SizeTerm(
                    name="lake_shore",
                    region=lakes.boundary,
                    size_m=lake_cfg.cell_size,
                    ramp_m=band if band is not None else 2.0 * lake_cfg.cell_size,
                )
            )
            if lake_cfg.interior_size is not None:
                terms.append(
                    SizeTerm(
                        name="lake_interior",
                        region=lakes,
                        size_m=lake_cfg.interior_size,
                        ramp_m=lake_cfg.buffer,
                    )
                )
        for label, geometry, size, buffer in inputs.lake_structures:
            if geometry is None or geometry.is_empty:
                continue
            terms.append(
                SizeTerm(
                    name=f"structure:{label}",
                    region=_dilated(geometry, buffer),
                    size_m=float(size),
                    ramp_m=float(buffer),
                )
            )
    for index, zone in enumerate(inputs.refinement_zones):
        terms.append(
            SizeTerm(
                name=f"zone:{index}",
                region=zone.region,
                size_m=zone.cell_size_m,
                ramp_m=zone.ramp_m,
            )
        )
    return terms


def _dilated(geometry: BaseGeometry, width: float) -> BaseGeometry:
    """A polygon as it is; a point or a line widened by *width* into a zone."""
    if geometry.geom_type in ("Polygon", "MultiPolygon") or width <= 0.0:
        return geometry
    return geometry.buffer(width)


def _outside(mesh_cfg: MeshConfig, inputs: PlanningInputs) -> OutsideCoarsening | None:
    """The outside coarsening, when a catchment is known and the factor coarsens."""
    if inputs.synthetic or inputs.watershed is None or mesh_cfg.outside_factor <= 1.0:
        return None
    return OutsideCoarsening(
        region=inputs.watershed,
        factor=mesh_cfg.outside_factor,
        transition_m=mesh_cfg.transition_distance,
    )


def _engine_options(mesh_cfg: MeshConfig, grid: RasterGridSpec) -> Mapping[str, object]:
    """The DEV options the built-in engine of *mesh_cfg* reads; a plugin gets none.

    A regular mesh with neither a shape nor a cell size is the DEM grid. A single
    cell size cannot name the pixels of a DEM whose steps differ, so the shape does.
    """
    if mesh_cfg.engine == "regular":
        if mesh_cfg.regular is not None:
            return {"shape": list(mesh_cfg.regular.shape)}
        return {} if mesh_cfg.cell_size else {"shape": [grid.nrow, grid.ncol]}
    triangle = mesh_cfg.triangle or MeshTriangleConfig()
    if mesh_cfg.engine == "triangle":
        return {"algorithm": triangle.algorithm}
    if mesh_cfg.engine == "voronoi":
        voronoi = mesh_cfg.voronoi or MeshVoronoiConfig()
        seeds = voronoi.seeds or ("generated" if triangle.path is None else "triangulation")
        return {"algorithm": triangle.algorithm, "seeds": seeds}
    return {}
