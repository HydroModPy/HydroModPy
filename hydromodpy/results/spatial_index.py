"""Point-in-cell lookup on unstructured meshes via Shapely STRtree."""

from __future__ import annotations

import warnings

import numpy as np

from hydromodpy.core.logging import get_logger

try:
    from shapely import STRtree
    from shapely.geometry import Polygon
except ImportError:
    STRtree = None
    Polygon = None

logger = get_logger(__name__)


def point_in_cell(
    vertices: np.ndarray,
    face_connectivity: np.ndarray,
    points: dict[str, tuple[float, float]],
    *,
    fill_value: int = -1,
) -> dict[str, int | None]:
    """Map observation points to mesh cell indices.

    Uses Shapely's STRtree for efficient spatial lookup on unstructured
    (tri/quad/mixed) meshes.

    Parameters
    ----------
    vertices : np.ndarray
        Node coordinates, shape ``(n_nodes, 2+)``. Only the first two
        columns (x, y) are used.
    face_connectivity : np.ndarray
        Cell-to-node connectivity, shape ``(n_cells, max_vpf)``.
        Padding value ``fill_value`` (default -1) for mixed meshes.
    points : dict[str, tuple[float, float]]
        Mapping of station id to ``(x, y)`` coordinates.
    fill_value : int
        Padding value in *face_connectivity* (default -1).

    Returns
    -------
    dict[str, int | None]
        Station id to cell index (0-based), or ``None`` if the point
        falls outside the mesh.
    """
    if STRtree is None:
        raise ImportError("shapely is required for point_in_cell")

    xy = vertices[:, :2]
    polys = []
    for row in face_connectivity:
        node_ids = row[row != fill_value]
        coords = xy[node_ids]
        polys.append(Polygon(coords))

    tree = STRtree(polys)
    result: dict[str, int | None] = {}

    for station_id, (px, py) in points.items():
        from shapely.geometry import Point

        pt = Point(px, py)
        idx = tree.query(pt, predicate="within")
        if len(idx) > 0:
            result[station_id] = int(idx[0])
        else:
            warnings.warn(
                f"Station '{station_id}' at ({px}, {py}) falls outside the mesh",
                stacklevel=2,
            )
            result[station_id] = None

    return result
