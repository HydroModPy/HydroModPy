"""The size terms of a graded mesh request.

A term refines the cells around a river, a barrier corner, a lake shore, a
structure or a refinement zone, or across a gap between two face lines
(``gap_size.py``). The outside coarsening widens the cells off the catchment.
"""

from __future__ import annotations

import shapely
from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry

from hydromodpy.core.logging import get_logger
from hydromodpy.spatial.mesh.mesh_config import MeshConfig
from hydromodpy.spatial.mesh.planning.gap_size import gap_terms
from hydromodpy.spatial.mesh.planning.geometry_cleanup import CLEANUP_PIXEL_SHARE
from hydromodpy.spatial.mesh.planning.inputs import PlanningInputs
from hydromodpy.spatial.mesh.planning.size_field import OutsideCoarsening, SizeTerm
from hydromodpy.spatial.mesh.request import BARRIER_FAMILY, LineFamilySpec
from hydromodpy.spatial.mesh.resample import kink_pieces

_logger = get_logger(__name__)


def river_size_m(mesh_cfg: MeshConfig, *, pixel: float) -> float:
    """Cell size along the rivers: ``river_cell_size``, else the pixel, never finer."""
    return max(mesh_cfg.river_cell_size or pixel, pixel)


def river_band_m(mesh_cfg: MeshConfig, *, h0: float) -> float:
    """Distance over which the size grows back from a river: ``river_band``, else ``2 * h0``."""
    return mesh_cfg.river_band if mesh_cfg.river_band is not None else 2.0 * h0


def refinement_terms(
    mesh_cfg: MeshConfig,
    inputs: PlanningInputs,
    families: tuple[LineFamilySpec, ...],
    *,
    h0: float,
    pixel: float,
) -> list[SizeTerm]:
    """The refinement terms: rivers, barrier corners, lake shore, interior and structures, zones.

    A zone drawn by a threshold that selected no pixel adds no term. The
    structures come from ``lake_structures.py``, which drops an empty one.
    """
    terms: list[SizeTerm] = _barrier_corner_terms(families, h0=h0, pixel=pixel)
    rivers = next((family for family in families if family.name == "rivers"), None)
    if rivers is not None:
        terms.append(
            SizeTerm(
                name="rivers",
                region=shapely.multilinestrings(rivers.lines),
                size_m=river_size_m(mesh_cfg, pixel=pixel),
                ramp_m=river_band_m(mesh_cfg, h0=h0),
            )
        )
    lake_cfg = mesh_cfg.lake_refinement
    if lake_cfg is not None:
        if inputs.lakes:
            lakes = shapely.union_all(inputs.lakes)
            terms.append(
                SizeTerm(
                    name="lake_shore",
                    region=lakes.boundary,
                    size_m=lake_cfg.cell_size,
                    ramp_m=lake_cfg.resolved_shoreline_band,
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
        for structure in inputs.lake_structures:
            terms.append(
                SizeTerm(
                    name=f"structure:{structure.label}",
                    region=_dilated(structure.geometry, structure.buffer_m),
                    size_m=float(structure.size_m),
                    ramp_m=float(structure.buffer_m),
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


def line_gap_terms(
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


def gap_notes(terms: list[SizeTerm], mesh_cfg: MeshConfig) -> tuple[str, ...]:
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


def outside_coarsening(mesh_cfg: MeshConfig, inputs: PlanningInputs) -> OutsideCoarsening | None:
    """The outside coarsening, when a catchment is known and the factor coarsens."""
    if inputs.synthetic or inputs.watershed is None or mesh_cfg.outside_factor <= 1.0:
        return None
    return OutsideCoarsening(
        region=inputs.watershed,
        factor=mesh_cfg.outside_factor,
        transition_m=mesh_cfg.transition_distance,
    )
