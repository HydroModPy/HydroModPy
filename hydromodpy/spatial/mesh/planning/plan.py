"""Turn ``[mesh]`` and the project inputs into one mesh request.

The planner fixes the intent of each line family, builds the size field of a
graded engine, which also follows the gaps between face lines (``gap_size.py``),
and resamples its lines at the local size, on the geometry cleaned first
(``geometry_cleanup.py``). A graded engine also gets the staircase of the catchment
outline smoothed, before anything reads it (``catchment_outline.py``). A
non-graded engine (``regular``) gets the raw lines and no size field. A
triangulation read from a file is meshed as it is: no size field, raw lines,
its own outline as the domain. A generated Voronoi mesh gets the lake shores it
can follow at its cell size (``lake_shores.py``) and the rivers off the lakes.
The line families are built in ``families.py`` and the size terms in
``size_terms.py``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np
from rasterio.features import rasterize
from shapely.geometry import Polygon

from hydromodpy.core.logging import get_logger
from hydromodpy.spatial.mesh import registry
from hydromodpy.spatial.mesh.mesh_config import MeshConfig, MeshTriangleConfig, MeshVoronoiConfig
from hydromodpy.spatial.mesh.planning.barrier_lines import split_barriers
from hydromodpy.spatial.mesh.planning.catchment_outline import smooth_catchment
from hydromodpy.spatial.mesh.planning.families import (
    follows_shores_by_pairs,
    requested_families,
    river_margin,
    with_shore_rings,
)
from hydromodpy.spatial.mesh.planning.geometry_cleanup import (
    CLEANUP_PIXEL_SHARE,
    GeometryCleanup,
    clean_lines,
    drop_small_holes,
)
from hydromodpy.spatial.mesh.planning.input_triangulation import domain_polygon_of
from hydromodpy.spatial.mesh.planning.inputs import PlanningInputs
from hydromodpy.spatial.mesh.planning.size_field import PixelRegion, SizeTerm, build_size_field
from hydromodpy.spatial.mesh.planning.size_terms import (
    gap_notes,
    line_gap_terms,
    outside_coarsening,
    refinement_terms,
)
from hydromodpy.spatial.mesh.request import LineFamilySpec, MeshRequest, RasterGridSpec, SizeField
from hydromodpy.spatial.mesh.resample import KINK_MIN_SHARE, node_tolerance, resample_families

__all__ = ["plan_mesh_request", "smoothed_catchment"]

_logger = get_logger(__name__)


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
    cleaned, for every engine (``geometry_cleanup.py``). The holes of the domain, the
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
    inputs = _smoothed_inputs(mesh_cfg, inputs, cleanup, pixel, graded=graded)
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
    graded = registry.get(mesh_cfg.engine).capabilities.graded
    smooth = _smoothed_inputs(mesh_cfg, inputs, cleanup, pixel, graded=graded)
    return None if smooth.watershed is inputs.watershed else smooth.watershed


def _smoothed_inputs(
    mesh_cfg: MeshConfig,
    inputs: PlanningInputs,
    cleanup: GeometryCleanup,
    pixel: float,
    *,
    graded: bool,
) -> PlanningInputs:
    """*inputs* with the catchment outline smoothed, for a graded engine that meshes the project."""
    if not graded or inputs.input_triangulation is not None:
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
    families = requested_families(mesh_cfg, inputs, domain, pixel=pixel)
    if not graded or inputs.input_triangulation is not None:
        return _Sizing(
            families=families,
            size_field=None,
            nominal=mesh_cfg.cell_size or pixel,
            notes=tuple(_ignored_settings(mesh_cfg, graded=graded)),
        )
    h0 = max(mesh_cfg.cell_size or pixel, pixel)
    terms = refinement_terms(mesh_cfg, inputs, families, h0=h0, pixel=pixel)

    def field(gaps: list[SizeTerm]) -> SizeField:
        return build_size_field(
            inputs.dem_grid,
            h0=h0,
            h_floor=pixel,
            terms=[*terms, *gaps],
            outside=outside_coarsening(mesh_cfg, inputs),
            max_slope=mesh_cfg.max_slope,
        )

    shore_notes: tuple[str, ...] = ()
    if follows_shores_by_pairs(mesh_cfg, inputs):
        # The gaps are those of the shores the mesh follows: an arm the
        # smoothing leaves out needs no cells.
        families, shore_notes = with_shore_rings(
            families, inputs, domain, field([]), margin=river_margin(mesh_cfg, pixel)
        )
    gaps = line_gap_terms(mesh_cfg, families, domain, h0=h0, pixel=pixel)
    size_field = field(gaps)
    notes = (*gap_notes(gaps, mesh_cfg), *shore_notes)
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
        transform=grid.transform,
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
