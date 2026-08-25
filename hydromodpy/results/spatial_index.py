"""Point-in-cell lookup on unstructured meshes, cached per mesh geometry.

Resolving a point to a cell means building a Shapely STRtree over every face
of the mesh. That build is the whole cost (~0.3 s for 27k faces, seconds for a
million-cell mesh) and it used to be paid again on every call. Two caches
remove it:

- an in-process locator cache, so several points, several variables or several
  runs sharing one mesh build the tree once per session;
- an on-disk map of already-resolved coordinates under
  ``<project>/.hmp/cache/cell_index/<fingerprint>.json``, so a second process
  (the next CLI call) answers without building anything.

Both are keyed by the geometry fingerprint of the run (its ``mesh_hash``), so
a mesh change invalidates them by construction rather than by policy. The
cache holds only what the mesh already implies; deleting it costs a rebuild.
"""

from __future__ import annotations

import json
import os
import warnings
from collections import OrderedDict
from collections.abc import Mapping
from pathlib import Path

import numpy as np

from hydromodpy.core.logging import get_logger
from hydromodpy.core.state.paths import internal_dir

try:
    from shapely import STRtree
    from shapely.geometry import Point, Polygon
except ImportError:
    STRtree = None
    Point = None
    Polygon = None

logger = get_logger(__name__)

CELL_INDEX_CACHE_DIRNAME = "cell_index"
"""Sub-directory of ``<project>/.hmp/cache`` holding the resolved-point maps."""

OUTSIDE = -1
"""On-disk marker for a coordinate that resolved to no cell."""

_MAX_CACHED_LOCATORS = 4
_LOCATORS: OrderedDict[str, CellLocator] = OrderedDict()


def cell_index_cache_dir(project_root: Path | str) -> Path:
    """Return ``<project>/.hmp/cache/cell_index``, the resolved-point cache."""
    return internal_dir(Path(project_root)) / "cache" / CELL_INDEX_CACHE_DIRNAME


def _coord_key(x: float, y: float) -> str:
    """Cache key of one coordinate pair, exact to the float."""
    return f"{float(x)!r},{float(y)!r}"


def _read_cache(path: Path | None) -> dict[str, int]:
    """Load a resolved-point map, returning an empty one on any failure."""
    if path is None or not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.debug("Unreadable cell-index cache, ignoring: %s", path)
        return {}
    points = payload.get("points")
    if not isinstance(points, dict):
        return {}
    return {str(k): int(v) for k, v in points.items()}


def _write_cache(path: Path, fingerprint: str, resolved: Mapping[str, int]) -> None:
    """Persist a resolved-point map atomically; a failure is never fatal."""
    payload = {"fingerprint": fingerprint, "points": dict(resolved)}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        logger.debug("Could not write cell-index cache: %s", path)


class CellLocator:
    """Point-to-cell resolver over one mesh.

    Parameters
    ----------
    vertices
        Node coordinates, shape ``(n_nodes, 2+)``. Only x and y are used.
    face_connectivity
        Cell-to-node connectivity, shape ``(n_cells, max_vpf)``, padded with
        ``fill_value`` on mixed meshes.
    fill_value
        Padding value in *face_connectivity*.
    fingerprint
        Geometry fingerprint of the mesh (a run's ``mesh_hash``). Required for
        any caching: without it every instance is standalone.
    cache_dir
        Directory of the on-disk resolved-point maps. ``None`` disables the
        persistent cache and keeps the in-process one.
    """

    def __init__(
        self,
        vertices: np.ndarray,
        face_connectivity: np.ndarray,
        *,
        fill_value: int = -1,
        fingerprint: str | None = None,
        cache_dir: Path | str | None = None,
    ) -> None:
        self._vertices = np.asarray(vertices)
        self._faces = np.asarray(face_connectivity)
        self._fill_value = int(fill_value)
        self._fingerprint = fingerprint
        self._cache_path: Path | None = None
        if fingerprint is not None and cache_dir is not None:
            self._cache_path = Path(cache_dir) / f"{fingerprint}.json"
        self._resolved: dict[str, int] = _read_cache(self._cache_path)
        self._tree: STRtree | None = None

    @property
    def n_cells(self) -> int:
        """Number of faces this locator can resolve into."""
        return int(self._faces.shape[0])

    @property
    def fingerprint(self) -> str | None:
        """Geometry fingerprint this locator and its caches are keyed by."""
        return self._fingerprint

    def _build_tree(self) -> STRtree:
        if self._tree is not None:
            return self._tree
        if STRtree is None:
            raise ImportError("shapely is required for point-in-cell lookup")
        xy = self._vertices[:, :2]
        polygons = [Polygon(xy[row[row != self._fill_value]]) for row in self._faces]
        self._tree = STRtree(polygons)
        return self._tree

    def locate(
        self,
        points: Mapping[str, tuple[float, float]],
        *,
        warn_outside: bool = True,
    ) -> dict[str, int | None]:
        """Map named points to cell indices, ``None`` when outside the mesh.

        Coordinates already present in the cache never touch the tree, so a
        repeated interrogation of the same piezometer costs one dict lookup.
        """
        result: dict[str, int | None] = {}
        pending: list[tuple[str, str, float, float]] = []
        for station_id, (px, py) in points.items():
            key = _coord_key(px, py)
            cached = self._resolved.get(key)
            if cached is None:
                pending.append((station_id, key, float(px), float(py)))
                continue
            result[station_id] = None if cached == OUTSIDE else int(cached)

        if pending:
            tree = self._build_tree()
            for station_id, key, px, py in pending:
                match = tree.query(Point(px, py), predicate="within")
                cell = int(match[0]) if len(match) > 0 else OUTSIDE
                self._resolved[key] = cell
                result[station_id] = None if cell == OUTSIDE else cell
            if self._cache_path is not None and self._fingerprint is not None:
                _write_cache(self._cache_path, self._fingerprint, self._resolved)

        if warn_outside:
            for station_id, cell in result.items():
                if cell is None:
                    px, py = points[station_id]
                    warnings.warn(
                        f"Station '{station_id}' at ({px}, {py}) falls outside the mesh",
                        stacklevel=2,
                    )
        return result


def locator_for(
    vertices: np.ndarray,
    face_connectivity: np.ndarray,
    *,
    fingerprint: str | None = None,
    cache_dir: Path | str | None = None,
    fill_value: int = -1,
) -> CellLocator:
    """Return a :class:`CellLocator`, reusing the one built for *fingerprint*.

    Without a fingerprint the mesh cannot be recognised, so a fresh locator is
    returned and nothing is cached.
    """
    if fingerprint is None:
        return CellLocator(vertices, face_connectivity, fill_value=fill_value)
    cached = _LOCATORS.get(fingerprint)
    if cached is not None:
        _LOCATORS.move_to_end(fingerprint)
        return cached
    locator = CellLocator(
        vertices,
        face_connectivity,
        fill_value=fill_value,
        fingerprint=fingerprint,
        cache_dir=cache_dir,
    )
    _LOCATORS[fingerprint] = locator
    while len(_LOCATORS) > _MAX_CACHED_LOCATORS:
        _LOCATORS.popitem(last=False)
    return locator


def clear_locator_cache() -> None:
    """Drop the in-process locator cache (the on-disk maps are untouched)."""
    _LOCATORS.clear()


def point_in_cell(
    vertices: np.ndarray,
    face_connectivity: np.ndarray,
    points: dict[str, tuple[float, float]],
    *,
    fill_value: int = -1,
    warn_outside: bool = True,
    fingerprint: str | None = None,
    cache_dir: Path | str | None = None,
) -> dict[str, int | None]:
    """Map observation points to mesh cell indices.

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
    warn_outside : bool
        Emit a warning for each point outside the mesh. An observation
        station outside the domain is a mistake worth reporting; a caller
        that sweeps a regular line across the domain (a cross-section)
        expects misses at both ends and turns this off.
    fingerprint : str, optional
        Geometry fingerprint of the mesh. Enables both caches.
    cache_dir : Path, optional
        Directory of the on-disk resolved-point maps.

    Returns
    -------
    dict[str, int | None]
        Station id to cell index (0-based), or ``None`` if the point
        falls outside the mesh.
    """
    locator = locator_for(
        vertices,
        face_connectivity,
        fingerprint=fingerprint,
        cache_dir=cache_dir,
        fill_value=fill_value,
    )
    return locator.locate(points, warn_outside=warn_outside)


__all__ = [
    "CELL_INDEX_CACHE_DIRNAME",
    "OUTSIDE",
    "CellLocator",
    "cell_index_cache_dir",
    "clear_locator_cache",
    "locator_for",
    "point_in_cell",
]
