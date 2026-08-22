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
    """
    cells: set[int] = set()
    by_lake = getattr(model, "lake_cell_ids_by_lake", None)
    if isinstance(by_lake, dict):
        for ids in by_lake.values():
            cells.update(int(cell) for cell in ids)
    if not cells:
        return None
    mask = np.zeros(int(n_cells), dtype=bool)
    inside = [cell for cell in cells if 0 <= cell < int(n_cells)]
    mask[inside] = True
    return mask


__all__ = ("observed_network_mask", "water_body_mask")
