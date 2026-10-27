"""Turn ``[mesh]`` and the project inputs into one mesh request.

The planner fixes the intent of each line family, builds the size field of a
graded engine, which also follows the gaps between face lines (``gap_size.py``),
and resamples its lines at the local size, on the geometry cleaned first
(``cleanup.py``). A graded engine also gets the staircase of the catchment
outline smoothed, before anything reads it (``catchment_outline.py``). A
non-graded engine (``regular``) gets the raw lines and no size field. A
triangulation read from a file is meshed as it is: no size field, raw lines,
its own outline as the domain. A generated Voronoi mesh gets the lake shores it can follow at its
cell size (``lake_shores.py``) and the rivers off the lakes.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace

import numpy as np
import shapely
from rasterio.features import rasterize
from rasterio.transform import Affine
from shapely.geometry import LineString, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import substring

from hydromodpy.core.logging import get_logger
from hydromodpy.spatial.mesh import registry
from hydromodpy.spatial.mesh.mesh_config import MeshConfig, MeshTriangleConfig, MeshVoronoiConfig
from hydromodpy.spatial.mesh.planning.barrier_lines import split_barriers
from hydromodpy.spatial.mesh.planning.catchment_outline import smooth_catchment
from hydromodpy.spatial.mesh.planning.cleanup import (
    CLEANUP_PIXEL_SHARE,
    GeometryCleanup,
    clean_lines,
    drop_small_holes,
)
from hydromodpy.spatial.mesh.planning.gap_size import gap_terms
from hydromodpy.spatial.mesh.planning.input_mesh import domain_polygon_of
from hydromodpy.spatial.mesh.planning.inputs import PlanningInputs
from hydromodpy.spatial.mesh.planning.lake_shores import followed_lake_shores
from hydromodpy.spatial.mesh.planning.size_field import (
    OutsideCoarsening,
    PixelRegion,
    SizeTerm,
    build_size_field,
)
from hydromodpy.spatial.mesh.request import (
    BARRIER_FAMILY,
    LineFamilySpec,
    MeshRequest,
    RasterGridSpec,
    SizeField,
)
from hydromodpy.spatial.mesh.resample import (
    KINK_MIN_SHARE,
    kink_pieces,
    node_tolerance,
    resample_families,
)

__all__ = ["plan_mesh_request", "smoothed_catchment"]

_logger = get_logger(__name__)

RIVER_STUB_SHARE = 0.25
"""Share of a river part between two lakes cut back at each end, when that is
less than the margin: the middle half keeps its river cells."""

RIVER_MARGIN_SHARE = 0.5
"""Distance between a lake outline and the rivers of a generated Voronoi mesh, in river cells.

On the Cheze reservoir the shores close from 0.5 river cell (40 m) on, and
not at 0 or 0.25: a river end on the ring cuts it, and its last seed takes the
shore pairs.
"""


def _pixel_size(grid: RasterGridSpec) -> float:
    """The DEM pixel size in metres: the larger step, so no cell is finer than a pixel."""
    return max(grid.dx, grid.dy)


@dataclass(frozen=True)
class _Sizing:
    """The families of a request as the engine meshes them, and the sizes they follow."""

    families: tuple[LineFamilySpec, ...]
    size_field: SizeField | None
    nominal: float
    notes: tuple[str, ...]

    def size_at(self, xy: np.ndarray) -> np.ndarray:
        """The local cell size [m] at points ``(k, 2)``: the size field, else the nominal size."""
        if self.size_field is None:
            return np.full(len(xy), self.nominal)
        return self.size_field.sample(xy)


def plan_mesh_request(mesh_cfg: MeshConfig, inputs: PlanningInputs) -> MeshRequest:
    """Return the request the engine of *mesh_cfg* meshes the project inputs with.

    A graded engine first gets the staircase of the catchment outline smoothed,
    where the mesh follows it (``catchment_outline.py``). Then the geometry is
    cleaned, for every engine (``cleanup.py``). The holes of the domain, the
    lakes and the catchment smaller than one local cell squared go: no cell
    fits in such a hole, and its ring only seeds cells a few metres apart.
    Then close vertices merge and loose line ends are cut back and snapped, at
    a tenth of the DEM pixel. The sizes are read again on the cleaned
    geometry. A triangulation read is meshed as it is.
    """
    graded = registry.get(mesh_cfg.engine).capabilities.graded
    triangulation = inputs.input_triangulation
    pixel = _pixel_size(inputs.dem_grid)
    cleanup = GeometryCleanup(tolerance=CLEANUP_PIXEL_SHARE * pixel)
    inputs = _smoothed_inputs(mesh_cfg, inputs, cleanup, pixel)
    domain = inputs.domain if triangulation is None else domain_polygon_of(triangulation)
    sizing = _sizing(mesh_cfg, inputs, domain, graded=graded, pixel=pixel)
    if triangulation is None:
        cleaned = drop_small_holes(inputs, sizing.size_at, cleanup)
        cleaned = clean_lines(cleaned, mesh_cfg.families, cleanup)
        if cleaned is not inputs:
            inputs = cleaned
            domain = inputs.domain
            sizing = _sizing(mesh_cfg, inputs, domain, graded=graded, pixel=pixel)
    cleanup.log()
    sized = sizing.size_field is not None
    return MeshRequest(
        domain=domain,
        crs_wkt=inputs.crs_wkt,
        grid=inputs.dem_grid,
        nominal_size_m=sizing.nominal,
        lines=sizing.families,
        size_field=sizing.size_field,
        seed=mesh_cfg.seed,
        options=_engine_options(mesh_cfg, inputs.dem_grid),
        input_triangulation=triangulation,
        notes=(
            *inputs.notes,
            *sizing.notes,
            *(_zone_notes(inputs) if sized else ()),
            *cleanup.notes(),
        ),
        source_runs=_source_runs(inputs) if sized else (),
    )


def smoothed_catchment(mesh_cfg: MeshConfig, inputs: PlanningInputs) -> Polygon | None:
    """The catchment outline :func:`plan_mesh_request` smooths for *inputs*, None when it does not.

    The mesh follows this outline, so a consumer that reads its cells against
    the catchment reads them against this one, and a cell and the polygon agree.
    None when the planner leaves the delineated polygon as it is: an engine that
    does not grade its cells, a triangulation read, an outline the mesh does not
    follow, an outline with no step to smooth. Holes the cleanup drops later,
    smaller than a local cell, are still in it.
    """
    pixel = _pixel_size(inputs.dem_grid)
    cleanup = GeometryCleanup(tolerance=CLEANUP_PIXEL_SHARE * pixel)
    smooth = _smoothed_inputs(mesh_cfg, inputs, cleanup, pixel)
    return None if smooth.watershed is inputs.watershed else smooth.watershed


def _smoothed_inputs(
    mesh_cfg: MeshConfig, inputs: PlanningInputs, cleanup: GeometryCleanup, pixel: float
) -> PlanningInputs:
    """*inputs* with the catchment outline smoothed, for a graded engine that meshes the project."""
    if inputs.input_triangulation is not None:
        return inputs
    if not registry.get(mesh_cfg.engine).capabilities.graded:
        return inputs
    return smooth_catchment(inputs, mesh_cfg.families, cleanup, pixel)


def _sizing(
    mesh_cfg: MeshConfig,
    inputs: PlanningInputs,
    domain: Polygon,
    *,
    graded: bool,
    pixel: float,
) -> _Sizing:
    """The families, size field and nominal size of *inputs* on *domain*.

    A graded engine gets the size field, its gap terms included, and the
    families resampled on it. A generated Voronoi mesh with lakes first
    picks the shores it follows on the field without gaps, then sizes the
    gaps of those shores. A barrier line that runs along a lake ring gets
    the ring vertices there. A triangulation read, and a non-graded engine,
    get the raw families and no field.
    """
    families = _families(mesh_cfg, inputs, domain, pixel=pixel)
    if not graded or inputs.input_triangulation is not None:
        return _Sizing(
            families=families,
            size_field=None,
            nominal=mesh_cfg.cell_size or pixel,
            notes=tuple(_ignored_settings(mesh_cfg, graded=graded)),
        )
    h0 = max(mesh_cfg.cell_size or pixel, pixel)
    terms = _size_terms(mesh_cfg, inputs, families, h0=h0, pixel=pixel)

    def field(gaps: list[SizeTerm]) -> SizeField:
        return build_size_field(
            inputs.dem_grid,
            h0=h0,
            h_floor=pixel,
            terms=[*terms, *gaps],
            outside=_outside(mesh_cfg, inputs),
            max_slope=mesh_cfg.max_slope,
        )

    shore_notes: tuple[str, ...] = ()
    if _follows_shores_by_pairs(mesh_cfg, inputs):
        # The gaps are those of the shores the mesh follows: an arm the
        # smoothing leaves out needs no cells.
        families, shore_notes = _followed_shores(
            families, inputs, domain, field([]), margin=_river_margin(mesh_cfg, pixel)
        )
    gaps = _gap_terms(mesh_cfg, families, domain, h0=h0, pixel=pixel)
    size_field = field(gaps)
    notes = (*_gap_notes(gaps, mesh_cfg), *shore_notes)
    split = split_barriers(
        families,
        node_tolerance(domain),
        shortest=lambda xy: KINK_MIN_SHARE * size_field.sample(xy),
    )
    resampled = resample_families(
        split.families, domain=domain, size_field=size_field, fixed_points=split.fixed_points
    )
    if resampled.short_fixed_edges:
        notes += (
            f"{resampled.short_fixed_edges} line edges between fixed nodes are shorter "
            "than 0.8 local cell and were kept whole",
        )
    return _Sizing(
        families=split.welded(resampled.families), size_field=size_field, nominal=h0, notes=notes
    )


def _followed_shores(
    families: tuple[LineFamilySpec, ...],
    inputs: PlanningInputs,
    domain: Polygon,
    size_field: SizeField,
    *,
    margin: float,
) -> tuple[tuple[LineFamilySpec, ...], tuple[str, ...]]:
    """The families with the lake rings a generated Voronoi mesh can follow, and the notes.

    The rivers also stay *margin* off the outlines the mesh follows: a river
    that crossed a ring would bend it at the crossing.
    """
    river_lines = inputs.river_trace.lines if inputs.river_trace is not None else ()
    shores = followed_lake_shores(
        inputs.lakes,
        size_field.sample,
        barriers=inputs.barriers,
        rivers=tuple(river_lines),
        finest=float(size_field.values.min()),
    )
    lines, _ = _clipped(_rings(shores.polygons), domain)
    if not lines:
        return families, ()
    rivers: tuple[LineString, ...] = ()
    if inputs.river_trace is not None:
        lakes = (*inputs.lakes, *shores.polygons)
        rivers = _rivers_off_lakes(inputs.river_trace.lines, lakes, domain, margin)
    out = []
    for family in families:
        if family.name == "lakes":
            out.append(replace(family, lines=lines))
        elif family.name == "rivers":
            if rivers:
                out.append(replace(family, lines=rivers))
        else:
            out.append(family)
    return tuple(out), shores.notes()


def _ignored_settings(mesh_cfg: MeshConfig, *, graded: bool) -> list[str]:
    """Notes on the grading settings an ungraded engine does not follow."""
    if graded:
        return []
    ignored = [
        name for name in ("river_cell_size", "river_band") if getattr(mesh_cfg, name) is not None
    ]
    if mesh_cfg.refinement_zone:
        ignored.append("refinement_zone")
    if not ignored:
        return []
    return [f"{mesh_cfg.engine} ignores {' and '.join(ignored)}: it does not grade its cells"]


def _families(
    mesh_cfg: MeshConfig, inputs: PlanningInputs, domain: Polygon, *, pixel: float
) -> tuple[LineFamilySpec, ...]:
    """The line families ``[mesh.families]`` asks for, clipped to *domain*."""
    wanted = mesh_cfg.families
    families: list[LineFamilySpec] = []
    if wanted.rivers == "cell" and inputs.river_trace is not None:
        if _follows_shores_by_pairs(mesh_cfg, inputs):
            margin = _river_margin(mesh_cfg, pixel)
            lines = _rivers_off_lakes(inputs.river_trace.lines, inputs.lakes, domain, margin)
        else:
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
    if wanted.barriers == "face" and inputs.barriers:
        lines, _ = _clipped(inputs.barriers, domain)
        if lines:
            families.append(LineFamilySpec(BARRIER_FAMILY, "face", lines))
    if wanted.watershed_boundary == "face" and inputs.watershed is not None:
        lines, _ = _clipped(_rings((inputs.watershed,)), domain)
        if lines:
            families.append(LineFamilySpec("watershed_boundary", "face", lines, closed=True))
    return tuple(families)


def _river_margin(mesh_cfg: MeshConfig, pixel: float) -> float:
    """How far [m] a river of a generated Voronoi mesh stays off the lake outlines.

    Half a river cell: a river that ends on a ring would cut it there into
    short segments, and its last seed would sit on the shore pairs.
    """
    return RIVER_MARGIN_SHARE * max(mesh_cfg.river_cell_size or pixel, pixel)


def _rivers_off_lakes(
    lines: Iterable[LineString], lakes: Iterable[BaseGeometry], domain: Polygon, margin: float
) -> tuple[LineString, ...]:
    """The parts of *lines* in *domain* off the *lakes*, each end on a lake cut back.

    A lake replaces the river in its footprint: the reaches stop at the shore
    and hand their flow to the lake, so a river chain there would only take the
    cells of the shore pairs. An end on a lake is cut back by *margin* [m], or
    by a quarter of the part when it is short: a link between two lakes keeps
    its river cells, which its reach needs.
    """
    union = shapely.union_all(list(lakes))
    parts, _ = _clipped(lines, domain.difference(union))
    touch = 1.0e-6 * max(margin, 1.0)
    kept = []
    for part in parts:
        length = part.length
        cut = min(margin, RIVER_STUB_SHARE * length)
        head = cut if union.distance(shapely.Point(part.coords[0])) <= touch else 0.0
        tail = cut if union.distance(shapely.Point(part.coords[-1])) <= touch else 0.0
        if length - head - tail > 0.0:
            kept.append(substring(part, head, length - tail))
    return tuple(kept)


def _follows_shores_by_pairs(mesh_cfg: MeshConfig, inputs: PlanningInputs) -> bool:
    """Whether the engine lays mirror pairs on lake shores: a generated Voronoi mesh with lakes."""
    return (
        mesh_cfg.engine == "voronoi"
        and mesh_cfg.families.lakes == "face"
        and inputs.input_triangulation is None
        and bool(inputs.lakes)
    )


def _rings(polygons: Iterable[BaseGeometry]) -> list[LineString]:
    """Every ring of *polygons* in normalized form, sorted, so their order never counts."""
    rings = []
    for polygon in shapely.get_parts(list(polygons)):
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
    """The refinement terms: rivers, barrier corners, lake shore, interior and structures, zones.

    A zone drawn by a threshold that selected no pixel adds no term.
    """
    terms: list[SizeTerm] = _barrier_corner_terms(families, h0=h0, pixel=pixel)
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
        if zone.region.is_empty:
            continue
        terms.append(
            SizeTerm(
                name=f"zone:{index}",
                region=zone.region,
                size_m=zone.cell_size_m,
                ramp_m=zone.ramp_m,
            )
        )
    return terms


def _source_runs(inputs: PlanningInputs) -> tuple[str, ...]:
    """The sim ids of the earlier runs whose fields drew a refinement zone."""
    return tuple(sorted({zone.source_run for zone in inputs.refinement_zones if zone.source_run}))


def _zone_notes(inputs: PlanningInputs) -> tuple[str, ...]:
    """One note per zone drawn by a threshold: the share of the catchment it covers.

    The share is that of the pixels of the catchment, or of the domain when
    no catchment is known. A zone that selects no pixel refines nothing.
    """
    zones = [
        (index, zone)
        for index, zone in enumerate(inputs.refinement_zones)
        if isinstance(zone.region, PixelRegion)
    ]
    if not zones:
        return ()
    grid = inputs.dem_grid
    area = inputs.watershed if inputs.watershed is not None else inputs.domain
    name = "catchment" if inputs.watershed is not None else "domain"
    inside = rasterize(
        [(area, 1)],
        out_shape=(grid.nrow, grid.ncol),
        transform=Affine(grid.dx, 0.0, grid.xmin, 0.0, -grid.dy, grid.ymax),
        fill=0,
        dtype="uint8",
    ).astype(bool)
    total = max(int(inside.sum()), 1)
    notes = []
    for index, zone in zones:
        share = float((zone.region.mask & inside).sum()) / total
        note = (
            f"refinement zone {index} ({zone.label}) selects no pixel and refines nothing"
            if zone.region.is_empty
            else f"refinement zone {index} ({zone.label}) covers {100.0 * share:.1f} % of "
            f"the {name}, at {zone.cell_size_m:g} m"
        )
        _logger.info("%s.", note[0].upper() + note[1:])
        notes.append(note)
    return tuple(notes)


def _gap_terms(
    mesh_cfg: MeshConfig,
    families: tuple[LineFamilySpec, ...],
    domain: Polygon,
    *,
    h0: float,
    pixel: float,
) -> list[SizeTerm]:
    """The terms of the gaps between the face lines and the domain outline (``gap_size.py``).

    Lines closer than the cleanup tolerance touch: no cell fits between them.
    """
    if mesh_cfg.gap_cells == 0.0:
        return []
    lines = [line for family in families if family.intent == "face" for line in family.lines]
    return gap_terms(
        lines,
        domain=domain,
        h0=h0,
        pixel=pixel,
        cells_across=mesh_cfg.gap_cells,
        touch=CLEANUP_PIXEL_SHARE * pixel,
    )


def _gap_notes(terms: list[SizeTerm], mesh_cfg: MeshConfig) -> tuple[str, ...]:
    """One note when the size follows a gap: how many chords, down to which size."""
    if not terms:
        return ()
    chords = sum(len(shapely.get_parts(term.region)) for term in terms)
    finest = min(term.size_m for term in terms)
    _logger.info(
        "The cell size follows %d gaps between face lines, down to %.1f m.", chords, finest
    )
    return (
        f"gaps: the cell size follows {chords} gaps between face lines or the domain "
        f"outline, {mesh_cfg.gap_cells:g} cells across, down to {finest:.1f} m",
    )


def _barrier_corner_terms(
    families: tuple[LineFamilySpec, ...], *, h0: float, pixel: float
) -> list[SizeTerm]:
    """One term per barrier line with a stretch between two corners shorter than *h0*.

    A barrier keeps its corners, so such a stretch is one segment: the cells
    within one stretch length of it are sized to that length and grow back at
    the largest slope. Without it a short joint between two long segments
    leaves no room for the faces that follow it. A stretch shorter than the
    pixel is left out: the resampling drops a corner no cell can resolve.
    """
    barrier = next((family for family in families if family.name == BARRIER_FAMILY), None)
    terms = []
    for index, line in enumerate(barrier.lines if barrier is not None else ()):
        short = [piece for piece in kink_pieces(line) if pixel <= piece.length < h0]
        if short:
            size = min(piece.length for piece in short)
            region = shapely.union_all([piece.buffer(piece.length) for piece in short])
            terms.append(SizeTerm(f"barrier_corner:{index}", region, size, 0.0))
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
        if seeds == "triangulation":
            return {"seeds": seeds}
        return {"seeds": seeds, "lloyd_tolerance": voronoi.lloyd_tolerance}
    return {}
