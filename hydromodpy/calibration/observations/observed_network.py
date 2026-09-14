"""The mapped stream network, projected onto the solver mesh.

The network is an input, taken for true. It is neither a product of the DEM nor
a quantity the method corrects: the paper poses it as "a selected stream
network independent of the DEM". What gets pre-treated when the two disagree is
the routing surface, not the data.

One projection serves both directions of the criterion. A cell belongs to the
network when the geometry intersects its polygon, never when it contains its
centroid: on a Voronoi mesh a line one cell wide loses about half its cells to
the centroid rule, and a half-cell bias on a single side of a criterion whose
zero is the equality of two terms moves the root.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from hydromodpy.core.logging import get_logger
from hydromodpy.spatial.mesh.ops.vector_cell_mask import cell_polygons, vector_cell_mask

logger = get_logger(__name__)


def _declared_crs(run_ctx: Any) -> str | None:
    """Return the projected CRS the run declares, if it declares one."""
    setup = getattr(getattr(run_ctx, "state", None), "setup", None)
    for holder in (setup, getattr(run_ctx, "setup", None)):
        geographic = getattr(holder, "geographic", None)
        crs = getattr(geographic, "crs_project", None) or getattr(geographic, "crs_proj", None)
        if crs:
            return str(crs)
    return None


def observed_network_mask(
    run_ctx: Any,
    output: Any,
    planar_mesh: Any,
    face_node_connectivity: np.ndarray,
) -> np.ndarray:
    """Project the declared stream geometry onto the mesh cells.

    Both CRS are required and the failure is loud: a silent mismatch produces a
    mask that is empty or plausible-but-wrong, and every distance downstream is
    reported in metres.
    """
    import geopandas as gpd

    path = getattr(output, "stream_geometry_path", None)
    if not path:
        raise ValueError(
            "the network criterion needs a mapped stream network: declare "
            "stream_geometry_path on the calibration output."
        )
    network = gpd.read_file(str(path))
    if network.empty:
        raise ValueError(f"the stream geometry {path!r} holds no feature.")
    if network.crs is None:
        raise ValueError(
            f"the stream geometry {path!r} declares no CRS, and the distances it feeds "
            "are reported in metres."
        )
    mesh_crs = _declared_crs(run_ctx)
    if not mesh_crs:
        raise ValueError(
            "the run declares no projected CRS, so the stream geometry cannot be placed "
            "on the mesh. Set [geographic] crs_project."
        )

    polygons = cell_polygons(np.asarray(planar_mesh.vertices, dtype=float), face_node_connectivity)
    mask = np.asarray(
        vector_cell_mask(
            polygons,
            list(network.geometry),
            mesh_crs=mesh_crs,
            geometry_crs=str(network.crs),
        ),
        dtype=bool,
    )
    logger.info(
        "Mapped stream network: %d feature(s) projected onto %d mesh cell(s).",
        len(network),
        int(mask.sum()),
    )
    return mask


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


def delineated_catchment_mask(
    run_ctx: Any,
    planar_mesh: Any,
    face_node_connectivity: np.ndarray,
) -> np.ndarray | None:
    """Project the catchment the geographic pipeline delineated onto the cells.

    That catchment is closed on the gauge the user declared and is delineated on
    the CONDITIONED routing surface. Re-deriving one by descending the model top
    instead gives the largest internal depression of an unconditioned surface: on
    a real basin it holds a few per cent of the mesh and none of the mapped
    network, and every trial then fails on an empty support.

    Returns ``None`` when the run declares no watershed, which is the case for a
    synthetic domain; the caller then falls back to descending to its own outlet.
    """
    import geopandas as gpd

    setup = getattr(getattr(run_ctx, "state", None), "setup", None) or getattr(
        run_ctx, "setup", None
    )
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
    # lie mostly outside the divide, and that ring is averaged into both D_so
    # and D_os and sets L_ref through reference_length.
    return vector_cell_mask(
        polygons,
        list(frame.geometry),
        mesh_crs=mesh_crs,
        geometry_crs=frame.crs,
        rule="centroid",
    )


__all__ = ("delineated_catchment_mask", "observed_network_mask", "water_body_mask")
