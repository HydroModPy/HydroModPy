"""Zone fractions of a spatial support on the cells of a planar cell mesh.

One answer for every solver: the share of each zone of a support in each cell.
Three sources, in order of trust:

1. The zone the mesh engine gave each cell (``PlanarCellMesh.cell_zone``). It is
   used when the engine declares exact faces, its zone names are zones of the
   support, and it names the majority zone of the support on at least 99 % of the
   cells. A contact drawn along mesh faces leaves no mixed cell, so the cell takes
   its zone whole. A mesh that disagrees more was not built on this map: the run
   stops.
2. The exact area of each zone polygon inside each cell, when the support carries
   vector zones (``zone_polygons``, a vector geology map).
3. The support's own sampling (``on_mesh``) otherwise: a raster map, and the
   analytical bands and rings, which keep their sampling.

The fractions of a cell are normalised by the area its zones cover, so a cell
half outside the map still sums to one; a cell no zone reaches sums to zero.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

import numpy as np
import shapely
from shapely.strtree import STRtree

from hydromodpy.core.exceptions import MeshError
from hydromodpy.spatial.field.meshes.field_mesh_adapter import to_field_mesh
from hydromodpy.spatial.mesh.model.planar_cell_mesh import PlanarCellMesh

__all__ = [
    "CELL_ZONE_AGREEMENT",
    "ZoneFractions",
    "ZonePolygons",
    "zone_fractions",
]

CELL_ZONE_AGREEMENT = 0.99
"""Smallest share of cells on which the engine zone must be the majority zone."""

_ORIGIN_STEP_M = 1000.0
"""Coordinates are shifted to an origin rounded to the km before any overlay."""

FractionSource = Literal["vector", "sampled"]


@dataclass(frozen=True)
class ZonePolygons:
    """The polygons of a vector zone map, one row per polygon part.

    ``geometries`` holds shapely polygons in the CRS of the mesh, ``zone_index``
    the index of each one's zone in ``zone_keys``. Two parts may share a zone.
    """

    geometries: np.ndarray
    zone_index: np.ndarray
    zone_keys: tuple[str, ...]

    def __post_init__(self) -> None:
        geometries = np.asarray(self.geometries, dtype=object).reshape(-1)
        zone_index = np.asarray(self.zone_index, dtype=np.int64).reshape(-1)
        if geometries.size != zone_index.size:
            raise ValueError(f"{geometries.size} polygon(s) for {zone_index.size} zone index(es)")
        if np.any((zone_index < 0) | (zone_index >= len(self.zone_keys))):
            raise ValueError("a polygon names a zone outside zone_keys")
        kinds = set(shapely.get_type_id(geometries).tolist()) if geometries.size else set()
        if not kinds <= {shapely.GeometryType.POLYGON.value}:
            raise ValueError("zone polygons must be single polygons; split multi-parts first")
        object.__setattr__(self, "geometries", geometries)
        object.__setattr__(self, "zone_index", zone_index)
        object.__setattr__(self, "zone_keys", tuple(str(key) for key in self.zone_keys))

    @classmethod
    def from_geometries(
        cls,
        geometries: Sequence[object],
        keys: Sequence[str],
        *,
        zone_keys: Sequence[str],
    ) -> ZonePolygons:
        """Split each (multi)polygon into parts and index its key in ``zone_keys``.

        An invalid polygon, a bow tie for one, is made valid first: it keeps the area
        the rasterization would have given it, and the exact cut does not stop on it.
        """
        zone_keys = tuple(str(key) for key in zone_keys)
        position = {key: index for index, key in enumerate(zone_keys)}
        unknown = sorted({str(key) for key in keys} - set(position))
        if unknown:
            raise ValueError(f"zone key(s) {unknown} are not in zone_keys")
        source = np.asarray(list(geometries), dtype=object)
        # A source polygon may cross itself; its exact cut needs a valid geometry.
        invalid = ~shapely.is_valid(source)
        if invalid.any():
            source = source.copy()
            source[invalid] = shapely.make_valid(source[invalid])
        source_zone = np.asarray([position[str(key)] for key in keys], dtype=np.int64)
        return cls._from_parts(source, source_zone, zone_keys)

    def clip_by_rect(self, xmin: float, ymin: float, xmax: float, ymax: float) -> ZonePolygons:
        """Keep the parts inside a box, cut to it: a map is read only where the mesh is."""
        if self.geometries.size == 0:
            return self
        hits = STRtree(self.geometries).query(shapely.box(xmin, ymin, xmax, ymax))
        hits = np.sort(hits)
        clipped = shapely.clip_by_rect(self.geometries[hits], xmin, ymin, xmax, ymax)
        return self._from_parts(clipped, self.zone_index[hits], self.zone_keys)

    @classmethod
    def _from_parts(
        cls, geometries: np.ndarray, zone_index: np.ndarray, zone_keys: tuple[str, ...]
    ) -> ZonePolygons:
        parts, owner = shapely.get_parts(geometries, return_index=True)
        # A collection (a clip touching a corner) holds lines and points too.
        nested = shapely.get_type_id(parts) == shapely.GeometryType.MULTIPOLYGON.value
        if nested.any():
            inner, inner_owner = shapely.get_parts(parts[nested], return_index=True)
            parts = np.concatenate([parts[~nested], inner])
            owner = np.concatenate([owner[~nested], owner[nested][inner_owner]])
        keep = (shapely.get_type_id(parts) == shapely.GeometryType.POLYGON.value) & ~(
            shapely.is_empty(parts)
        )
        return cls(
            geometries=parts[keep],
            zone_index=np.asarray(zone_index, dtype=np.int64)[owner[keep]],
            zone_keys=zone_keys,
        )


@dataclass(frozen=True)
class ZoneFractions:
    """The share of each zone in each cell, and where it came from.

    ``values`` is ``(n_cells, n_zones)``, its columns in ``zone_keys`` order.
    ``source`` says how the cells outside the engine zones were read, and
    ``n_engine_cells`` how many cells took the engine zone whole.
    """

    zone_keys: tuple[str, ...]
    values: np.ndarray
    source: FractionSource
    n_engine_cells: int

    def by_zone(self) -> dict[str, np.ndarray]:
        """One fraction column per zone key."""
        return {key: self.values[:, index] for index, key in enumerate(self.zone_keys)}

    @property
    def n_mixed_cells(self) -> int:
        """Cells shared by at least two zones."""
        return int(np.count_nonzero(np.count_nonzero(self.values > 0.0, axis=1) > 1))


def zone_fractions(cell_mesh: PlanarCellMesh, support: object) -> ZoneFractions:
    """Return the share of each zone of ``support`` in each cell of ``cell_mesh``."""
    polygons = getattr(support, "zone_polygons", None)
    if polygons is not None:
        keys, values = polygons.zone_keys, _vector_fractions(cell_mesh, polygons)
        source: FractionSource = "vector"
    else:
        keys, values = _sampled_fractions(cell_mesh, support)
        source = "sampled"
    return _with_engine_zones(cell_mesh, support, keys, values, source)


def _vector_fractions(cell_mesh: PlanarCellMesh, zones: ZonePolygons) -> np.ndarray:
    """Exact area of each zone in each cell, over the area the zones cover.

    Every pair of a cell and a part whose boxes overlap is sorted by prepared
    predicates: a cell inside the part counts whole, a cell that only touches
    it counts nothing, and only the cells the part boundary crosses are cut.
    """
    n_cells = cell_mesh.n_cells
    areas = np.zeros((n_cells, len(zones.zone_keys)), dtype=float)
    if zones.geometries.size == 0:
        return areas
    origin = np.floor(cell_mesh.centers.min(axis=0) / _ORIGIN_STEP_M) * _ORIGIN_STEP_M
    cells = _cell_polygons(cell_mesh, origin)
    parts = shapely.transform(zones.geometries, lambda xy: xy - origin)
    cell_hit, part_hit = STRtree(parts).query(cells)
    shapely.prepare(parts)

    inside = shapely.contains_properly(parts[part_hit], cells[cell_hit])
    shared = np.where(inside, shapely.area(cells)[cell_hit], 0.0)
    rest = np.flatnonzero(~inside)
    cut = rest[shapely.intersects(parts[part_hit[rest]], cells[cell_hit[rest]])]
    shared[cut] = shapely.area(shapely.intersection(cells[cell_hit[cut]], parts[part_hit[cut]]))
    np.add.at(areas, (cell_hit, zones.zone_index[part_hit]), shared)

    covered = areas.sum(axis=1)
    reached = covered > 0.0
    areas[reached] /= covered[reached, None]
    return areas


def _cell_polygons(cell_mesh: PlanarCellMesh, origin: np.ndarray) -> np.ndarray:
    """One shapely polygon per cell, shifted by ``-origin``, from the padded connectivity."""
    padded = np.asarray(cell_mesh.geometry.padded_connectivity, dtype=np.int64)
    valid = padded >= 0
    owner = np.broadcast_to(np.arange(padded.shape[0])[:, None], padded.shape)[valid]
    coords = np.asarray(cell_mesh.mesh.vertices, dtype=float)[padded[valid], :2] - origin
    return shapely.polygons(shapely.linearrings(coords, indices=owner))


def _sampled_fractions(
    cell_mesh: PlanarCellMesh, support: object
) -> tuple[tuple[str, ...], np.ndarray]:
    """The support's own sampling, at the density it declares."""
    n_samples = int(getattr(support, "default_cell_samples_per_axis", 8) or 8)
    discretization = support.on_mesh(to_field_mesh(cell_mesh.mesh), cell_samples_per_axis=n_samples)
    keys, by_zone = discretization.weighted_components()
    values = np.column_stack([np.asarray(by_zone[key], dtype=float).reshape(-1) for key in keys])
    return tuple(str(key) for key in keys), values


def _with_engine_zones(
    cell_mesh: PlanarCellMesh,
    support: object,
    keys: tuple[str, ...],
    values: np.ndarray,
    source: FractionSource,
) -> ZoneFractions:
    """Give each cell its engine zone whole, when the engine can be trusted with it."""
    unused = ZoneFractions(zone_keys=keys, values=values, source=source, n_engine_cells=0)
    cell_zone = cell_mesh.cell_zone
    exact = bool(cell_mesh.qa.declarations.get("exact_faces", False))
    if not exact or cell_zone is None or not cell_mesh.zone_names:
        return unused
    if not set(cell_mesh.zone_names) <= set(keys):
        return unused

    column_of_name = np.asarray([keys.index(name) for name in cell_mesh.zone_names])
    named = np.flatnonzero(cell_zone >= 0)
    engine_column = column_of_name[cell_zone[named]]
    covered = values[named].sum(axis=1) > 0.0
    agree = values[named].argmax(axis=1) == engine_column
    n_compared = int(np.count_nonzero(covered))
    share = float(np.count_nonzero(agree & covered)) / n_compared if n_compared else 1.0
    if share < CELL_ZONE_AGREEMENT:
        support_id = getattr(support, "identifier", "<unnamed>")
        raise MeshError(
            f"The mesh engine '{cell_mesh.identity.engine_id}' gives its zone to "
            f"{named.size} cell(s), but that zone is the majority zone of spatial support "
            f"'{support_id}' on only {share:.1%} of them (at least "
            f"{CELL_ZONE_AGREEMENT:.0%} expected). The mesh was not built on this map: "
            "mesh the domain with the geology the parameters read."
        )
    one_hot = values.copy()
    one_hot[named] = 0.0
    one_hot[named, engine_column] = 1.0
    return ZoneFractions(zone_keys=keys, values=one_hot, source=source, n_engine_cells=named.size)
