"""The mapped stream network, projected onto the solver mesh.

The network is an input, taken for true. It is neither a product of the DEM nor
a quantity the method corrects: the paper poses it as "a selected stream
network independent of the DEM". What gets pre-treated when the two disagree is
the routing surface, not the data.

One projection serves both directions of the criterion, and it must draw the
map as thin as the model draws its own network. The simulated network is a
chain of the descent graph, one cell wide; the criterion's zero is the equality
of two mean distances, so a map drawn thicker than that chain moves the root
with no hydrogeological reason.

The default rule, ``"crossing"``, keeps the cell holding each point where a
line crosses the segment joining two edge-sharing cell centres. On a
structured grid it is WhiteboxTools ``VectorLinesToRaster``, the tool of
Abherve et al. (2023), and a model that reproduces the map exactly scores
J = 0 in D8 as in D4. ``"touch"`` keeps every cell the line intersects,
corners included: each diagonal step of the map gains the two cells sharing
the corner, D_os grows while D_so stays at zero, and the search pulls K down on
a perfect match. It is kept to replay a session recorded before 2026-09.

Neither rule is the centroid rule, which on a Voronoi mesh drops about half the
cells of a line one cell wide.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

from hydromodpy.core.logging import get_logger
from hydromodpy.core.stream_criterion_defaults import (
    STREAM_CRITERION_DEFAULTS,
    ObservedRasterization,
)
from hydromodpy.spatial.mesh.ops.vector_cell_mask import (
    cell_polygons,
    line_crossing_cell_mask,
    vector_cell_mask,
)

if TYPE_CHECKING:
    from hydromodpy.calibration.observations.network_source import ObservedNetwork
    from hydromodpy.simulation.planning.plan import RunContext

logger = get_logger(__name__)


@dataclass(frozen=True)
class ObservedNetworkMask:
    """The mapped network drawn on the mesh cells, and what the drawing cost.

    ``n_fallback_parts`` counts the reaches that crossed no centre segment and
    were kept at the cell holding their midpoint; ``n_outside_parts`` the
    reaches that entered no mesh cell and were left out. Both are zero under
    the touch rule, which has no such case.
    """

    mask: np.ndarray
    rasterization: ObservedRasterization
    n_fallback_parts: int = 0
    n_outside_parts: int = 0


def _declared_crs(run_ctx: RunContext) -> str | None:
    """Return the projected CRS the run declares, if it declares one."""
    geographic = getattr(run_ctx.state.setup, "geographic", None)
    crs = getattr(geographic, "crs_project", None) or getattr(geographic, "crs_proj", None)
    return str(crs) if crs else None


def observed_network_mask(
    run_ctx: RunContext,
    observed: ObservedNetwork,
    planar_mesh: Any,
    face_node_connectivity: np.ndarray,
    *,
    rasterization: ObservedRasterization = STREAM_CRITERION_DEFAULTS.observed_rasterization,
    cell_centres: np.ndarray | None = None,
) -> ObservedNetworkMask:
    """Project the resolved stream geometry onto the mesh cells.

    ``observed`` is a fully resolved :class:`ObservedNetwork`, from any of the
    three sources ``resolve_observed_network`` accepts: this function never
    reads a path itself and never re-derives a geometry. Both CRS are still
    required and the failure is loud: a silent mismatch produces a mask that
    is empty or plausible-but-wrong, and every distance downstream is reported
    in metres.

    ``rasterization`` picks the rule of the module docstring. The crossing
    rule joins the points the criterion samples the top at: ``cell_centres``
    when given, else the solver mesh's ``cell_centroids()``, the generator
    seeds on a Voronoi mesh.
    """
    if rasterization not in ("crossing", "touch"):
        raise ValueError(
            f"observed_rasterization must be 'crossing' or 'touch', got {rasterization!r}."
        )
    frame = observed.geometry
    if frame is None or len(frame) == 0:
        raise ValueError(f"the {observed.source} network holds no feature.")
    if observed.crs is None:
        raise ValueError(
            f"the {observed.source} network declares no CRS, and the distances it feeds "
            "are reported in metres."
        )
    mesh_crs = _declared_crs(run_ctx)
    if not mesh_crs:
        raise ValueError(
            "the run declares no projected CRS, so the stream geometry cannot be placed "
            "on the mesh. Set [geographic] crs_project."
        )

    vertices = np.asarray(planar_mesh.vertices, dtype=float)
    polygons = cell_polygons(vertices, face_node_connectivity)
    n_fallback = 0
    n_outside = 0
    if rasterization == "touch":
        mask = np.asarray(
            vector_cell_mask(
                polygons,
                list(frame.geometry),
                mesh_crs=mesh_crs,
                geometry_crs=observed.crs,
            ),
            dtype=bool,
        )
    else:
        crossed = line_crossing_cell_mask(
            polygons,
            vertices,
            face_node_connectivity,
            _criterion_centres(run_ctx, cell_centres),
            list(frame.geometry),
            mesh_crs=mesh_crs,
            geometry_crs=observed.crs,
        )
        mask = np.asarray(crossed.mask, dtype=bool)
        n_fallback = crossed.n_fallback_parts
        n_outside = crossed.n_outside_parts
        if n_outside:
            logger.warning(
                "Mapped stream network (%s): %d reach(es) cross no centre segment and enter "
                "no mesh cell, so no cell holds them and the criterion leaves them out. "
                "They lie off the mesh, often in the sliver between the clip polygon and "
                "the cells.",
                observed.source,
                n_outside,
            )
    logger.info(
        "Mapped stream network (%s%s): %d feature(s) projected onto %d mesh cell(s) by the "
        "%s rule%s%s.",
        observed.source,
        ", clipped" if observed.clipped else "",
        len(frame),
        int(mask.sum()),
        rasterization,
        (
            f", {n_fallback} reach(es) crossing no centre segment kept at their midpoint cell"
            if n_fallback
            else ""
        ),
        f", from {observed.path}" if observed.path else "",
    )
    return ObservedNetworkMask(
        mask=mask,
        rasterization=rasterization,
        n_fallback_parts=int(n_fallback),
        n_outside_parts=int(n_outside),
    )


def _criterion_centres(run_ctx: RunContext, cell_centres: np.ndarray | None) -> np.ndarray:
    """Return the points the criterion samples the top at, one per cell."""
    if cell_centres is not None:
        return np.asarray(cell_centres, dtype=float)
    solver_mesh = getattr(getattr(run_ctx, "model", None), "solver_mesh", None)
    centroids = getattr(solver_mesh, "cell_centroids", None)
    if not callable(centroids):
        raise ValueError(
            "the crossing rule joins the cell centres the solver mesh sampled its top at, "
            "and the run's solver mesh exposes no 'cell_centroids' method."
        )
    return np.asarray(centroids(), dtype=float)


def water_body_mask(model: Any, *, n_cells: int) -> np.ndarray | None:
    """Return the cells whose surface-water extent is an input of the model.

    The generic name is not "lake": it is every cell whose water extent the
    model is told rather than asked. A trace of hydrography drawn across a
    reservoir is not the observation of a stream, and a lake cell exchanging
    water is not a hillslope seepage, so those cells leave both supports. They
    stay in the graph, because a hillslope cell upstream of the reservoir has
    to be able to descend through it, and they stay in the target, because open
    water is surface water and must absorb the path.

    This is the same cut the stream-network builder already applies on the
    simulated side, where a reach is cut at the lake cell and its flow handed
    over at the shoreline. One rule, two consumers.

    The backend publishes that footprint as ``open_water_cell_ids``: every lake
    cell of the run, whether the lake is solved as an inactive fixed-area
    reservoir or kept active for its varying level. Reading the inactive subset
    instead would leave a marnage reservoir inside both supports, and the
    question asked here is whether the cell is open water, not how the lake is
    discretised.
    """
    ids = getattr(model, "open_water_cell_ids", None)
    if ids is None:
        return None
    limit = int(n_cells)
    inside = sorted({int(cell) for cell in ids if 0 <= int(cell) < limit})
    if not inside:
        return None
    mask = np.zeros(limit, dtype=bool)
    mask[inside] = True
    return mask


def delineated_outlet_xy(run_ctx: RunContext) -> tuple[float, float] | None:
    """Return the outlet the geographic step delineated from, in the project CRS.

    That is the snapped pour point, not the declared one: the snap moved the
    declared outlet onto the strongest accumulation of the routing DEM, and the
    catchment was closed there. The criterion moves it once more, within two
    cells, onto the most accumulated cell of its own graph.

    Returns ``None`` when the catchment came from a drawn polygon rather than
    from a point, or when the run carries no geographic step.
    """
    geographic = getattr(run_ctx.state.setup, "geographic", None)
    x = getattr(geographic, "x_outlet_snapped", None)
    y = getattr(geographic, "y_outlet_snapped", None)
    if x is None or y is None:
        return None
    point = (float(x), float(y))
    return point if np.all(np.isfinite(point)) else None


def delineated_catchment_mask(
    run_ctx: RunContext,
    planar_mesh: Any,
    face_node_connectivity: np.ndarray,
) -> np.ndarray | None:
    """Project the catchment the geographic pipeline delineated onto the cells.

    The criterion does not score this polygon. It scores the cells upstream of
    the outlet on its own conditioned graph, and reads this projection only to
    close on it when no outlet point exists and to publish how far the two
    differ (``catchment_mismatch``).

    Returns ``None`` when the run declares no watershed, which is the case for a
    synthetic domain; the caller then closes on the largest basin of its graph.
    """
    import geopandas as gpd

    setup = run_ctx.state.setup
    # ``setup.geographic`` is the delineation object, the same handle
    # spatial.geographic.structure_binders reads the catchment from.
    shp = getattr(getattr(setup, "geographic", None), "watershed_shp", None)
    if shp is None or not Path(str(shp)).exists():
        return None

    frame = gpd.read_file(str(shp))
    if frame.empty:
        return None
    mesh_crs = _declared_crs(run_ctx)
    if not mesh_crs:
        return None

    polygons = cell_polygons(np.asarray(planar_mesh.vertices, dtype=float), face_node_connectivity)
    # A catchment is areal, so a cell belongs to it when its CENTRE is inside.
    # The touch rule of the linework would add one exterior ring of cells that
    # lie mostly outside the divide, and that ring would read as a mismatch
    # against the graph catchment that is not one.
    return vector_cell_mask(
        polygons,
        list(frame.geometry),
        mesh_crs=mesh_crs,
        geometry_crs=frame.crs,
        rule="centroid",
    )


__all__ = (
    "ObservedNetworkMask",
    "delineated_catchment_mask",
    "delineated_outlet_xy",
    "observed_network_mask",
    "water_body_mask",
)
