"""The planar cell mesh: the one object a mesh engine returns and a consumer reads.

``PlanarCellMesh`` wraps a planar ``HydroMesh`` (geometry and connectivity,
unchanged) and adds what the solvers and the consumers share: the single cell
center rule, the CRS, the line families, the zones, the engine identity and the
quality report. Derived geometry is computed once, on first access.
"""

from __future__ import annotations

import functools
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Literal, get_args

import numpy as np

from hydromodpy.mesh.planar.cell_types import CellType
from hydromodpy.mesh.planar.geometry import DerivedGeometry, derive_geometry
from hydromodpy.mesh.planar.hydro_mesh import HydroMesh
from hydromodpy.mesh.planar.quality import MeshQA, compute_mesh_qa

if TYPE_CHECKING:
    from numpy.typing import ArrayLike
    from shapely.geometry import LineString, Polygon

__all__ = [
    "CellChain",
    "CenterKind",
    "FaceFamilyTable",
    "MeshIdentity",
    "PlanarCellMesh",
    "build_planar_cell_mesh",
]

CenterKind = Literal["generator", "cell_center", "vertex_mean"]

_CELL_TYPES = frozenset({CellType.QUADRILATERAL, CellType.TRIANGLE, CellType.POLYGON})

_ROW_COLUMNS = ("cell_a", "cell_b", "node_a", "node_b", "zone_left", "zone_right")
"""The columns of a face family table a family gives, one entry per row."""


@dataclass(frozen=True)
class MeshIdentity:
    """Which engine built a mesh, from which request, with which seed.

    ``request_hash`` is the sha256 hex of the canonical request, empty for a mesh
    adapted from a legacy producer. ``seed`` is ``None`` for an engine without
    random draws.
    """

    engine_id: str
    engine_version: str
    request_hash: str
    seed: int | None

    def __post_init__(self) -> None:
        """Refuse an anonymous engine."""
        if not self.engine_id.strip() or not self.engine_version.strip():
            raise ValueError("engine_id and engine_version must be non-empty")


@dataclass(frozen=True, eq=False)
class CellChain:
    """One ordered chain of cells of a cell family, upstream to downstream.

    A cell may repeat only at a confluence. ``offset_m`` gives, per entry of
    ``cell_ids``, the distance [m] from the cell center to the source line; it is
    ``None`` when the engine publishes no lateral offset (the cell holds the line).
    A crossing cell, taken by a chain although its center lies off the line, has
    an offset above zero.
    """

    family: str
    chain_id: int
    cell_ids: np.ndarray
    offset_m: np.ndarray | None = None

    def __post_init__(self) -> None:
        """Normalize the cell ids to a 1-D int64 array and the offsets to float64."""
        cell_ids = np.asarray(self.cell_ids, dtype=np.int64).reshape(-1)
        if not self.family.strip():
            raise ValueError("a cell chain needs a family name")
        if cell_ids.size and int(cell_ids.min()) < 0:
            raise ValueError(f"chain {self.chain_id} of '{self.family}' has a negative cell id")
        object.__setattr__(self, "cell_ids", cell_ids)
        if self.offset_m is None:
            return
        offset_m = np.asarray(self.offset_m, dtype=np.float64).reshape(-1)
        if offset_m.size != cell_ids.size:
            raise ValueError(
                f"chain {self.chain_id} of '{self.family}' has {cell_ids.size} cells "
                f"but {offset_m.size} offsets"
            )
        if offset_m.size and not (np.all(np.isfinite(offset_m)) and float(offset_m.min()) >= 0.0):
            raise ValueError(
                f"chain {self.chain_id} of '{self.family}' has an offset that is negative or not finite"
            )
        object.__setattr__(self, "offset_m", offset_m)


@dataclass(frozen=True, eq=False)
class FaceFamilyTable:
    """Every family face: one row per mesh edge lying on a family line.

    ``cell_a`` is the cell on the left of the oriented source line and ``cell_b``
    the cell on its right, ``-1`` on the domain boundary. ``zone_left`` and
    ``zone_right`` index ``PlanarCellMesh.zone_names``, ``-1`` when unknown.
    """

    names: tuple[str, ...]
    family: np.ndarray
    cell_a: np.ndarray
    cell_b: np.ndarray
    node_a: np.ndarray
    node_b: np.ndarray
    zone_left: np.ndarray
    zone_right: np.ndarray

    def __post_init__(self) -> None:
        """Cast the columns, check their lengths and their id ranges."""
        columns = {
            "family": np.int16,
            "cell_a": np.int64,
            "cell_b": np.int64,
            "node_a": np.int64,
            "node_b": np.int64,
            "zone_left": np.int32,
            "zone_right": np.int32,
        }
        for name, dtype in columns.items():
            object.__setattr__(self, name, np.asarray(getattr(self, name), dtype=dtype).ravel())
        object.__setattr__(self, "names", tuple(self.names))
        lengths = {getattr(self, name).size for name in columns}
        if len(lengths) != 1:
            raise ValueError("face family columns must have one length")
        if len(set(self.names)) != len(self.names):
            raise ValueError(f"face family names repeat: {self.names}")
        if self.n_rows == 0:
            return
        if int(self.family.min()) < 0 or int(self.family.max()) >= len(self.names):
            raise ValueError("face family index outside names")
        if int(self.cell_a.min()) < 0 or int(self.cell_b.min()) < -1:
            raise ValueError("cell_a must be a cell id, cell_b a cell id or -1")
        if int(min(self.node_a.min(), self.node_b.min())) < 0:
            raise ValueError("face node ids must be non-negative")
        if int(min(self.zone_left.min(), self.zone_right.min())) < -1:
            raise ValueError("zone indices must be -1 or more")

    @property
    def n_rows(self) -> int:
        """Number of family faces."""
        return int(self.family.size)

    @classmethod
    def stack(cls, families: Sequence[tuple[str, Mapping[str, ArrayLike]]]) -> FaceFamilyTable:
        """Return the table of the rows of each family, family after family.

        Each family is its name and its columns ``cell_a``, ``cell_b``,
        ``node_a`` and ``node_b``, one entry per row. ``zone_left`` and
        ``zone_right`` are ``-1`` where a family leaves them out. A family
        without a row keeps its name and its index.
        """
        sizes = [np.asarray(columns["cell_a"]).size for _, columns in families]

        def column(key: str) -> np.ndarray:
            parts = [
                np.asarray(columns[key]).ravel() if key in columns else np.full(size, -1)
                for (_, columns), size in zip(families, sizes, strict=True)
            ]
            return np.concatenate(parts) if parts else np.empty(0, dtype=np.int64)

        return cls(
            names=tuple(name for name, _ in families),
            family=np.repeat(np.arange(len(families)), sizes),
            **{key: column(key) for key in _ROW_COLUMNS},
        )


@dataclass(frozen=True, eq=False)
class PlanarCellMesh:
    """A planar mesh of cells with its centers, CRS, families, identity and QA.

    ``centers`` is the only cell center rule for every consumer: the Voronoi
    generator, the regular cell center or the triangle vertex mean, as
    ``center_kind`` says. Boundary sides are face families named
    ``boundary:<label>`` with ``cell_b = -1``. ``smoothed_catchment`` is the
    outline of the catchment the planner smoothed before meshing, in the CRS of
    the mesh, None when the mesh follows the delineated polygon as it is: a
    cell is read against that outline, which its faces follow.
    """

    mesh: HydroMesh
    centers: np.ndarray
    center_kind: CenterKind
    crs_wkt: str
    identity: MeshIdentity
    qa: MeshQA
    cell_chains: tuple[CellChain, ...] = ()
    face_families: FaceFamilyTable | None = None
    cell_zone: np.ndarray | None = None
    zone_names: tuple[str, ...] = ()
    structured_shape: tuple[int, int] | None = None
    smoothed_catchment: Polygon | None = None

    def __post_init__(self) -> None:
        """Check the invariants every consumer relies on."""
        mesh = self.mesh
        if mesh.ndim != 2:
            raise ValueError("a planar cell mesh needs 2-column vertices")
        if len(mesh.cell_blocks) != 1 or mesh.cell_types[0] not in _CELL_TYPES:
            raise ValueError(
                "a planar cell mesh holds one block of quadrilaterals, triangles or polygons"
            )
        if self.center_kind not in get_args(CenterKind):
            raise ValueError(f"unknown center_kind '{self.center_kind}'")
        if not isinstance(self.crs_wkt, str) or not self.crs_wkt.strip():
            raise ValueError("a planar cell mesh needs a CRS (crs_wkt is empty)")
        n_cells = mesh.n_cells
        centers = np.asarray(self.centers, dtype=np.float64)
        if centers.shape != (n_cells, 2) or not np.all(np.isfinite(centers)):
            raise ValueError(f"centers must be finite with shape ({n_cells}, 2)")
        object.__setattr__(self, "centers", centers)
        object.__setattr__(self, "cell_chains", tuple(self.cell_chains))
        object.__setattr__(self, "zone_names", tuple(self.zone_names))
        for chain in self.cell_chains:
            if chain.cell_ids.size and int(chain.cell_ids.max()) >= n_cells:
                raise ValueError(f"chain {chain.chain_id} of '{chain.family}' names a cell id >= n")
        self._check_face_families(n_cells)
        self._check_cell_zone(n_cells)
        if self.structured_shape is not None:
            nrow, ncol = (int(v) for v in self.structured_shape)
            if nrow * ncol != n_cells or mesh.cell_types[0] is not CellType.QUADRILATERAL:
                raise ValueError("structured_shape needs nrow * ncol quadrilaterals")
            object.__setattr__(self, "structured_shape", (nrow, ncol))

    def _check_face_families(self, n_cells: int) -> None:
        table = self.face_families
        if table is None or table.n_rows == 0:
            return
        if int(max(table.cell_a.max(), table.cell_b.max())) >= n_cells:
            raise ValueError("a face family names a cell id >= n_cells")
        if int(max(table.node_a.max(), table.node_b.max())) >= self.mesh.n_nodes:
            raise ValueError("a face family names a vertex id >= n_nodes")
        if int(max(table.zone_left.max(), table.zone_right.max())) >= len(self.zone_names):
            raise ValueError("a face family names a zone outside zone_names")

    def _check_cell_zone(self, n_cells: int) -> None:
        if self.cell_zone is None:
            return
        zones = np.asarray(self.cell_zone, dtype=np.int32).ravel()
        if zones.size != n_cells:
            raise ValueError(f"cell_zone must have {n_cells} values, got {zones.size}")
        if zones.size and (int(zones.min()) < -1 or int(zones.max()) >= len(self.zone_names)):
            raise ValueError("cell_zone holds an index outside zone_names")
        object.__setattr__(self, "cell_zone", zones)

    @property
    def n_cells(self) -> int:
        """Number of cells."""
        return self.mesh.n_cells

    def with_smoothed_catchment(self, outline: Polygon | None) -> PlanarCellMesh:
        """This mesh with the catchment outline the planner smoothed for it, geometry kept."""
        return self._replaced(smoothed_catchment=outline)

    def with_qa(self, qa: MeshQA) -> PlanarCellMesh:
        """This mesh with another quality report, geometry kept."""
        return self._replaced(qa=qa)

    def _replaced(self, **changes: object) -> PlanarCellMesh:
        """A copy with ``changes``, carrying the derived geometry when it is computed."""
        mesh = replace(self, **changes)
        if "geometry" in self.__dict__:
            mesh.__dict__["geometry"] = self.__dict__["geometry"]
        return mesh

    @functools.cached_property
    def geometry(self) -> DerivedGeometry:
        """Areas, edges and adjacency, derived once."""
        return derive_geometry(self.mesh)

    @property
    def connectivity_rows(self) -> np.ndarray:
        """Return the cells as one ``(n_cells, k)`` array, the format of the Zarr store.

        A triangle or quadrilateral block is returned as the mesh holds it; a
        polygon block, ``-1`` padded, as 32-bit node ids.
        """
        if self.mesh.cell_types[0].is_ragged:
            return self.geometry.padded_connectivity
        return np.asarray(self.mesh.flat_connectivity)

    def chains(self, family: str) -> tuple[CellChain, ...]:
        """Return the cell chains of one family."""
        return tuple(chain for chain in self.cell_chains if chain.family == family)

    def face_rows(self, family: str) -> np.ndarray:
        """Return a boolean mask over the face family rows of one family."""
        table = self.face_families
        if table is None:
            return np.zeros(0, dtype=bool)
        if family not in table.names:
            return np.zeros(table.n_rows, dtype=bool)
        return table.family == table.names.index(family)

    def family_cells(self, family: str) -> np.ndarray:
        """Return the unique cells of one family: chain cells and both face sides."""
        parts = [chain.cell_ids for chain in self.chains(family)]
        if self.face_families is not None:
            rows = self.face_rows(family)
            parts += [self.face_families.cell_a[rows], self.face_families.cell_b[rows]]
        if not parts:
            return np.empty(0, dtype=np.int64)
        cells = np.concatenate(parts)
        return np.unique(cells[cells >= 0])


def build_planar_cell_mesh(
    mesh: HydroMesh,
    centers: np.ndarray,
    *,
    center_kind: CenterKind,
    crs_wkt: str,
    identity: MeshIdentity,
    declarations: Mapping[str, bool],
    geometry: DerivedGeometry | None = None,
    cell_chains: Sequence[CellChain] = (),
    face_families: FaceFamilyTable | None = None,
    cell_zone: np.ndarray | None = None,
    zone_names: Sequence[str] = (),
    structured_shape: tuple[int, int] | None = None,
    domain_area_m2: float | None = None,
    lines: Mapping[str, Sequence[LineString]] | None = None,
    target_size: np.ndarray | None = None,
    notes: Sequence[str] = (),
    extras: Mapping[str, float] | None = None,
) -> PlanarCellMesh:
    """Derive the geometry, measure the QA and assemble the planar cell mesh.

    The derived geometry the QA was measured on becomes the mesh geometry, so it
    is computed once; a caller that already derived it passes it as ``geometry``.
    ``target_size`` is the size [m] asked for at each cell center, for the QA
    ``size_fidelity``.
    """
    if geometry is None:
        geometry = derive_geometry(mesh)
    qa = compute_mesh_qa(
        mesh,
        centers,
        geometry,
        declarations=declarations,
        domain_area_m2=domain_area_m2,
        lines=lines,
        cell_chains=cell_chains,
        face_families=face_families,
        target_size=target_size,
        notes=notes,
        extras=extras,
    )
    cell_mesh = PlanarCellMesh(
        mesh=mesh,
        centers=centers,
        center_kind=center_kind,
        crs_wkt=crs_wkt,
        identity=identity,
        qa=qa,
        cell_chains=tuple(cell_chains),
        face_families=face_families,
        cell_zone=cell_zone,
        zone_names=tuple(zone_names),
        structured_shape=structured_shape,
    )
    cell_mesh.__dict__["geometry"] = geometry
    return cell_mesh
