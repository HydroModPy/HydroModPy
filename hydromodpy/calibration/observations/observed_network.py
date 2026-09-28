"""The mapped stream network, projected onto the solver mesh.

The network is an input, taken for true. It is neither a product of the DEM nor
a quantity the method corrects: the paper poses it as "a selected stream
network independent of the DEM". What gets pre-treated when the two disagree is
the routing surface, not the data.

The one exception is asked for by name: ``[geographic.snap_streams]`` snaps
the projection made here onto the talwegs of the criterion graph
(:mod:`hydromodpy.core.stream_snap`). ``diagnose`` publishes what the snap
would move and scores this projection; ``apply`` scores the snapped map. Either
way the projection itself is what this module returns, and the displacement is
published.

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
            _report_unplaced_reaches(run_ctx, observed, polygons, vertices, mesh_crs, n_outside)
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


_UNPLACED_REPORTS: dict[tuple[Any, ...], tuple[int, int, float]] = {}
"""The unplaced-reach counts already reported in this process, by placement.

A calibration builds the network criterion once per trial on the same map and
the same mesh. The geometry work behind the report (reprojection, a cell
tree, the catchment read from disk) then runs once, and the report is logged
once; later builds of the same placement only log at DEBUG.
"""

_UNPLACED_REPORTS_MAX = 32


def _report_unplaced_reaches(
    run_ctx: RunContext,
    observed: ObservedNetwork,
    polygons: np.ndarray,
    vertices: np.ndarray,
    mesh_crs: str,
    n_outside: int,
) -> None:
    """Say which of the reaches that enter no mesh cell matter.

    A map is often drawn wider than the catchment, so reaches off the model
    domain are expected and are logged at INFO. A reach inside the domain that
    still enters no cell lies in the sliver between the domain outline and the
    cells: the model holds that stream and the criterion does not see it, so
    only those reaches are worth a warning, with their count and length.

    A map clipped to the catchment lies inside the domain by construction. An
    unclipped map on a run without a delineated catchment has no outline to
    test against, and its reaches are read as off the domain.

    Both counts and the length come from one list of unplaced parts, so the
    printed count and length always describe the same reaches.
    """
    key = _placement_key(run_ctx, observed, polygons, vertices, mesh_crs, n_outside)
    known = _UNPLACED_REPORTS.get(key)
    if known is not None:
        logger.debug(
            "Mapped stream network (%s): placement unchanged since the last build, "
            "%d reach(es) inside and %d outside the model domain enter no mesh cell.",
            observed.source,
            known[0],
            known[1],
        )
        return
    unplaced = _unplaced_parts(observed, polygons, mesh_crs)
    if observed.clipped:
        inside_lengths = [float(part.length) for part in unplaced]
    else:
        outline = _domain_outline(run_ctx, mesh_crs)
        inside_lengths = (
            []
            if outline is None
            else [
                float(part.intersection(outline).length)
                for part in unplaced
                if part.intersects(outline)
            ]
        )
    n_inside = len(inside_lengths)
    n_off = len(unplaced) - n_inside
    if len(_UNPLACED_REPORTS) >= _UNPLACED_REPORTS_MAX:
        _UNPLACED_REPORTS.clear()
    _UNPLACED_REPORTS[key] = (n_inside, n_off, float(sum(inside_lengths)))
    if n_off:
        logger.info(
            "Mapped stream network (%s): %d reach(es) lie outside the model domain and enter "
            "no mesh cell, so the criterion leaves them out, as expected for a map wider than "
            "the catchment.",
            observed.source,
            n_off,
        )
    if n_inside:
        logger.warning(
            "Mapped stream network (%s): %d reach(es) inside the model domain, %.0f m in all, "
            "enter no mesh cell, so the criterion leaves them out. They lie in the sliver "
            "between the domain outline and the cells.",
            observed.source,
            n_inside,
            sum(inside_lengths),
        )


def _placement_key(
    run_ctx: RunContext,
    observed: ObservedNetwork,
    polygons: np.ndarray,
    vertices: np.ndarray,
    mesh_crs: str,
    n_outside: int,
) -> tuple[Any, ...]:
    """Fingerprint what decides which reaches enter no cell: the map, the mesh, the outline."""
    import hashlib

    frame = observed.geometry
    mesh_digest = hashlib.blake2b(
        np.ascontiguousarray(vertices, dtype=float).tobytes(), digest_size=16
    ).hexdigest()
    shp = getattr(getattr(run_ctx.state.setup, "geographic", None), "watershed_shp", None)
    outline_stamp: tuple[str, float] | None = None
    if shp is not None and not observed.clipped:
        path = Path(str(shp))
        outline_stamp = (str(path), path.stat().st_mtime if path.exists() else -1.0)
    return (
        observed.source,
        str(observed.path),
        bool(observed.clipped),
        str(observed.crs),
        len(frame),
        tuple(float(value) for value in frame.total_bounds),
        str(mesh_crs),
        int(polygons.shape[0]),
        mesh_digest,
        outline_stamp,
        int(n_outside),
    )


def _unplaced_parts(observed: ObservedNetwork, polygons: np.ndarray, mesh_crs: str) -> list[Any]:
    """Return the line parts of the map, in the mesh CRS, that touch no cell polygon.

    The parts are split as the crossing rule splits them: every line of a
    multi-part or collection geometry, with a positive length.
    """
    import geopandas as gpd
    import shapely
    from shapely.strtree import STRtree

    series = gpd.GeoSeries(list(observed.geometry.geometry), crs=observed.crs).to_crs(mesh_crs)
    parts: list[Any] = []
    pending = [geometry for geometry in series if geometry is not None]
    while pending:
        geometry = pending.pop(0)
        for part in shapely.get_parts(geometry):
            if part.geom_type in ("MultiLineString", "GeometryCollection"):
                pending.append(part)
            elif (
                part.geom_type in ("LineString", "LinearRing")
                and not part.is_empty
                and part.length > 0.0
            ):
                parts.append(part)
    cells = [polygon for polygon in polygons if polygon is not None]
    if not parts or not cells:
        return parts
    hit, _ = STRtree(cells).query(parts, predicate="intersects")
    touched = set(int(index) for index in hit)
    return [part for index, part in enumerate(parts) if index not in touched]


def _domain_outline(run_ctx: RunContext, mesh_crs: str) -> Any | None:
    """Return the delineated catchment in the mesh CRS, or None when the run has none."""
    import geopandas as gpd
    import shapely

    shp = getattr(getattr(run_ctx.state.setup, "geographic", None), "watershed_shp", None)
    if shp is None or not Path(str(shp)).exists():
        return None
    frame = gpd.read_file(str(shp))
    if frame.empty or frame.crs is None:
        return None
    return shapely.union_all(list(frame.to_crs(mesh_crs).geometry))


def resolve_minimal_network(run_ctx: RunContext, output: Any) -> ObservedNetwork | None:
    """Return the minimal (permanent) map a network output declares, or None.

    The map arrives as it is: a file, or the permanent reaches the hydrography
    data family wrote beside its network. Neither is filtered by an attribute
    here, so the criterion scores the same geometry whatever drew it.
    """
    from hydromodpy.calibration.observations.network_source import (
        UnresolvedObservedNetwork,
        resolve_network_file,
        resolve_network_role,
    )

    choice = getattr(output, "minimal_observed_network", None)
    path = getattr(output, "minimal_stream_geometry_path", None)
    if choice == "data.hydrography":
        resolved = resolve_network_role(
            run_ctx,
            "reference_permanent",
            canonical_source="data.hydrography",
            message_source="minimal_observed_network = 'data.hydrography'",
            empty_reason="the permanent part of the loaded network carries no feature",
        )
        if resolved is None:
            raise UnresolvedObservedNetwork(
                "minimal_observed_network = 'data.hydrography' names the permanent reaches of "
                "the hydrography network, and this project holds none: the loader writes them "
                "only when its source says which reaches flow all year. Give the permanent "
                "map as a file in 'minimal_stream_geometry_path'."
            )
        return resolved
    if not path:
        return None
    return resolve_network_file(
        path,
        message_source=f"minimal_stream_geometry_path = {path!r}",
        empty_reason="the file carries no feature",
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
    "resolve_minimal_network",
    "water_body_mask",
)
