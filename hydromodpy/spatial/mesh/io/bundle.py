"""Read self-contained catchment mesh exchange bundles, and their cell mesh.

A bundle is a folder of CSV files (``nodes``, ``cells``, ``edges``) and a
``metadata.json``. No mesh engine writes one any more: a run stores its cells
in ``fields.zarr`` and the solvers get them as a ``PlanarCellMesh``. The reader
stays for the bundles that are written by hand and committed:

- the Boussinesq validation cases, which write them with
  ``validation_cases/shared`` and keep 16 of them in ``mesh_bundles/``;
- ``Boussinesq`` itself, which reads one from ``output_exchange_bundle_dir`` of
  the mesh summary (``flow_to_boussinesq_adapter.resolve_mesh_bundle``);
- :func:`cell_mesh_from_bundle`, which turns a bundle into a ``PlanarCellMesh``
  for the mesh tests.

The format is versioned. ``metadata.json`` declares its version in
``bundle_schema_version``, which is :data:`BUNDLE_SCHEMA_VERSION` for every
bundle this reader reads, and names its CRS in ``crs`` and its files in
``files``. :data:`BUNDLE_COLUMNS` lists the columns of each CSV file with
their meaning and unit, and a column it marks optional may be absent or left
empty.

The reader depends only on the Python standard library.
:func:`cell_mesh_from_bundle` reads the nodes, triangles and edges of a bundle
as a ``PlanarCellMesh``: the nodes and the triangles in the order of the files,
the vertex means as centres, the flagged edges as the ``rivers`` face family and
the boundary edges that lie on the bounding box as the ``boundary:<side>``
families.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

import numpy as np

from hydromodpy.spatial.mesh.model.cell_types import CellType
from hydromodpy.spatial.mesh.model.geometry import BOX_SIDES, box_side_of_edges
from hydromodpy.spatial.mesh.model.hydro_mesh import CellBlock, HydroMesh
from hydromodpy.spatial.mesh.model.planar_cell_mesh import (
    FaceFamilyTable,
    MeshIdentity,
    PlanarCellMesh,
    build_planar_cell_mesh,
)

BUNDLE_SCHEMA_VERSION: Final[str] = "mesh_catchment_bundle_v1"
"""Version of the bundle format, as ``metadata.json`` declares it."""

OPTIONAL: Final[str] = "optional"
"""Word that opens the description of a column a bundle may leave out."""

BUNDLE_COLUMNS: Final[dict[str, dict[str, str]]] = {
    "nodes.csv": {
        "node_id": "Index of the node, from 0, in the order of the file",
        "x": "x coordinate of the node, m, in the CRS of metadata.json",
        "y": "y coordinate of the node, m, in the CRS of metadata.json",
        "z_top": f"{OPTIONAL}: top elevation at the node, m",
        "z_bottom": f"{OPTIONAL}: bottom elevation at the node, m",
    },
    "cells.csv": {
        "cell_id": "Index of the cell, from 0, in the order of the file",
        "geom_type": "Shape of the cell, such as triangle or polygon",
        "ncvert": f"{OPTIONAL}: number of nodes of the cell; without it, every filled n<k> counts",
        "n<k>": "Node ids of the cell in order around it, from n0; the columns past ncvert are empty",
        "centroid_x": "x coordinate of the cell centre, m",
        "centroid_y": "y coordinate of the cell centre, m",
        "area_m2": "Area of the cell, m2",
        "z_top_centroid": f"{OPTIONAL}: top elevation at the cell centre, m",
        "z_top_mean": f"{OPTIONAL}: mean top elevation over the cell, m",
        "z_bottom_centroid": f"{OPTIONAL}: bottom elevation at the cell centre, m",
        "z_bottom_mean": f"{OPTIONAL}: mean bottom elevation over the cell, m",
        "geology_code": f"{OPTIONAL}: integer code of the geology of the cell",
        "geology_key": f"{OPTIONAL}: name of the geology of the cell",
        "hydraulic_conductivity_m_s": f"{OPTIONAL}: hydraulic conductivity of the cell, m/s",
        "storage_coefficient": f"{OPTIONAL}: storage coefficient of the cell, dimensionless",
    },
    "edges.csv": {
        "edge_id": "Index of the edge, from 0, in the order of the file",
        "node_a": "Node id at one end of the edge",
        "node_b": "Node id at the other end of the edge",
        "cell_a": "Cell id on one side of the edge",
        "cell_b": f"{OPTIONAL}: cell id on the other side, empty on the boundary",
        "length_m": "Length of the edge, m",
        "edge_kind": "internal or boundary",
        "is_river": f"{OPTIONAL}: true when the edge lies on a river",
        "geology_a_key": f"{OPTIONAL}: name of the geology on the side of cell_a",
        "geology_b_key": f"{OPTIONAL}: name of the geology on the side of cell_b",
    },
    "cell_geology_fractions.csv": {
        "cell_id": "Cell id",
        "geology_key": "Name of one geology the cell holds",
        "fraction": "Share of the cell area that geology covers, from 0 to 1",
    },
}
"""Columns of each CSV file of a bundle, with their meaning and unit.

``n<k>`` stands for ``n0``, ``n1`` and so on, as many as the largest cell
needs. ``cell_geology_fractions.csv`` is optional as a whole.
"""


def _parse_optional_float(raw_value: str) -> float | None:
    """Parse one CSV field where the empty string means "missing"."""
    text = str(raw_value).strip()
    if text == "":
        return None
    return float(text)


def _parse_optional_int(raw_value: str) -> int | None:
    """Parse one integer CSV field where the empty string means "missing"."""
    text = str(raw_value).strip()
    if text == "":
        return None
    return int(text)


def _parse_bool(raw_value: str) -> bool:
    """Parse permissive CSV booleans used by the bundle export."""
    return str(raw_value).strip().lower() in {"1", "true", "yes", "on"}


def _as_dict(raw_value: object) -> dict[str, Any]:
    """Return one plain dictionary from a loose JSON-like object."""
    return dict(raw_value) if isinstance(raw_value, dict) else {}


def _as_text_tuple(raw_value: object) -> tuple[str, ...]:
    """Return one tuple of strings from a loose JSON list/tuple field."""
    if not isinstance(raw_value, (list, tuple)):
        return ()
    return tuple(str(value) for value in raw_value)


@dataclass(frozen=True)
class CatchmentMeshBundleNode:
    """One exported mesh node with optional top and bottom elevations."""

    node_id: int
    x: float
    y: float
    z_top: float | None
    z_bottom: float | None


@dataclass(frozen=True)
class CatchmentMeshBundleCell:
    """One exported 2D cell with geometry, geology and hydraulic summaries."""

    cell_id: int
    geom_type: str
    node_indices: tuple[int, ...]
    centroid_x: float
    centroid_y: float
    area_m2: float
    z_top_centroid: float | None
    z_top_mean: float | None
    z_bottom_centroid: float | None
    z_bottom_mean: float | None
    geology_code: int | None
    geology_key: str
    hydraulic_conductivity_m_s: float | None
    storage_coefficient: float | None


@dataclass(frozen=True)
class CatchmentMeshBundleEdge:
    """One exported mesh edge with adjacency and river/interface flags."""

    edge_id: int
    node_a: int
    node_b: int
    cell_a: int
    cell_b: int | None
    length_m: float
    edge_kind: str
    is_river: bool
    geology_a_key: str
    geology_b_key: str


@dataclass(frozen=True)
class CatchmentMeshBundleGeologyFraction:
    """One non-zero geology fraction attached to one exported cell."""

    cell_id: int
    geology_key: str
    fraction: float


@dataclass(frozen=True)
class CatchmentMeshBundleFilesView:
    """Typed view of the exported filenames declared in ``metadata.json``."""

    mesh: str = "mesh_2d.msh"
    nodes: str | None = None
    cells: str | None = None
    edges: str | None = None
    cell_geology_fractions: str | None = None
    metadata: str | None = None
    readme: str | None = None
    mesh_summary: str | None = None

    @classmethod
    def from_mapping(
        cls,
        raw_value: object,
    ) -> CatchmentMeshBundleFilesView:
        payload = _as_dict(raw_value)
        return cls(
            mesh=str(payload.get("mesh", "mesh_2d.msh")),
            nodes=_optional_text(payload.get("nodes")),
            cells=_optional_text(payload.get("cells")),
            edges=_optional_text(payload.get("edges")),
            cell_geology_fractions=_optional_text(payload.get("cell_geology_fractions")),
            metadata=_optional_text(payload.get("metadata")),
            readme=_optional_text(payload.get("readme")),
            mesh_summary=_optional_text(payload.get("mesh_summary")),
        )


@dataclass(frozen=True)
class CatchmentMeshBundleGeologyView:
    """Typed view of the geology metadata carried by one bundle."""

    available: bool = False
    field_id: str | None = None
    source_kind: str | None = None
    cell_samples_per_axis: int | None = None
    zone_keys: tuple[str, ...] = ()

    @classmethod
    def from_mapping(
        cls,
        raw_value: object,
    ) -> CatchmentMeshBundleGeologyView:
        payload = _as_dict(raw_value)
        return cls(
            available=bool(payload.get("available", False)),
            field_id=_optional_text(payload.get("field_id")),
            source_kind=_optional_text(payload.get("source_kind")),
            cell_samples_per_axis=_parse_optional_int(
                ""
                if payload.get("cell_samples_per_axis") is None
                else str(payload.get("cell_samples_per_axis"))
            ),
            zone_keys=_as_text_tuple(payload.get("zone_keys")),
        )


@dataclass(frozen=True)
class CatchmentMeshBundleTopographyView:
    """Typed view of the topography metadata carried by one bundle."""

    source_path: str | None = None
    node_field: str | None = None
    cell_fields: tuple[str, ...] = ()

    @classmethod
    def from_mapping(
        cls,
        raw_value: object,
    ) -> CatchmentMeshBundleTopographyView:
        payload = _as_dict(raw_value)
        return cls(
            source_path=_optional_text(payload.get("source_path")),
            node_field=_optional_text(payload.get("node_field")),
            cell_fields=_as_text_tuple(payload.get("cell_fields")),
        )


@dataclass(frozen=True)
class CatchmentMeshBundleVerticalView:
    """Typed view of the vertical/discretization metadata carried by one bundle."""

    available: bool = False
    surface_name: str | None = None
    derived_from: str | None = None
    node_field: str | None = None
    cell_fields: tuple[str, ...] = ()
    depth_model: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(
        cls,
        raw_value: object,
    ) -> CatchmentMeshBundleVerticalView:
        payload = _as_dict(raw_value)
        raw_depth_model = payload.get("depth_model")
        depth_model = _as_dict(raw_depth_model)
        return cls(
            available=bool(payload.get("available", False)),
            surface_name=_optional_text(payload.get("surface_name")),
            derived_from=_optional_text(payload.get("derived_from")),
            node_field=_optional_text(payload.get("node_field")),
            cell_fields=_as_text_tuple(payload.get("cell_fields")),
            depth_model=depth_model,
        )


@dataclass(frozen=True)
class CatchmentMeshBundleHydraulicPropertyView:
    """Typed view of one hydraulic-property metadata block."""

    available: bool = False
    unit: str | None = None
    values_source: str | None = None
    values_csv_file: str | None = None
    default_value: float | None = None
    zone_keys_defined: tuple[str, ...] = ()
    missing_zone_keys: tuple[str, ...] = ()

    @classmethod
    def from_mapping(
        cls,
        raw_value: object,
    ) -> CatchmentMeshBundleHydraulicPropertyView:
        payload = _as_dict(raw_value)
        default_value_raw = payload.get("default_value")
        default_value = None if default_value_raw is None else float(default_value_raw)
        return cls(
            available=bool(payload.get("available", False)),
            unit=_optional_text(payload.get("unit")),
            values_source=_optional_text(payload.get("values_source")),
            values_csv_file=_optional_text(payload.get("values_csv_file")),
            default_value=default_value,
            zone_keys_defined=_as_text_tuple(payload.get("zone_keys_defined")),
            missing_zone_keys=_as_text_tuple(payload.get("missing_zone_keys")),
        )


@dataclass(frozen=True)
class CatchmentMeshBundleHydraulicPropertiesView:
    """Typed view of the hydraulic-properties metadata carried by one bundle."""

    available: bool = False
    averaging: str | None = None
    cell_fields: tuple[str, ...] = ()
    conductivity: CatchmentMeshBundleHydraulicPropertyView = field(
        default_factory=CatchmentMeshBundleHydraulicPropertyView
    )
    storage_coefficient: CatchmentMeshBundleHydraulicPropertyView = field(
        default_factory=CatchmentMeshBundleHydraulicPropertyView
    )

    @classmethod
    def from_mapping(
        cls,
        raw_value: object,
    ) -> CatchmentMeshBundleHydraulicPropertiesView:
        payload = _as_dict(raw_value)
        return cls(
            available=bool(payload.get("available", False)),
            averaging=_optional_text(payload.get("averaging")),
            cell_fields=_as_text_tuple(payload.get("cell_fields")),
            conductivity=CatchmentMeshBundleHydraulicPropertyView.from_mapping(
                payload.get("conductivity")
            ),
            storage_coefficient=CatchmentMeshBundleHydraulicPropertyView.from_mapping(
                payload.get("storage_coefficient")
            ),
        )


@dataclass(frozen=True)
class CatchmentMeshBundleMetadataView:
    """Typed convenience view over the otherwise raw ``metadata.json`` payload."""

    bundle_schema_version: str | None = None
    mesh_kind: str | None = None
    cell_type: str | None = None
    indexing: str | None = None
    crs: str | None = None
    n_nodes: int | None = None
    n_cells: int | None = None
    constraints_mode: str | None = None
    source_mesh_path: str | None = None
    files: CatchmentMeshBundleFilesView = field(default_factory=CatchmentMeshBundleFilesView)
    geology: CatchmentMeshBundleGeologyView = field(default_factory=CatchmentMeshBundleGeologyView)
    topography: CatchmentMeshBundleTopographyView = field(
        default_factory=CatchmentMeshBundleTopographyView
    )
    vertical: CatchmentMeshBundleVerticalView = field(
        default_factory=CatchmentMeshBundleVerticalView
    )
    hydraulic_properties: CatchmentMeshBundleHydraulicPropertiesView = field(
        default_factory=CatchmentMeshBundleHydraulicPropertiesView
    )

    @classmethod
    def from_mapping(
        cls,
        raw_value: object,
    ) -> CatchmentMeshBundleMetadataView:
        payload = _as_dict(raw_value)
        return cls(
            bundle_schema_version=_optional_text(payload.get("bundle_schema_version")),
            mesh_kind=_optional_text(payload.get("mesh_kind")),
            cell_type=_optional_text(payload.get("cell_type")),
            indexing=_optional_text(payload.get("indexing")),
            crs=_optional_text(payload.get("crs")),
            n_nodes=_coerce_optional_int(payload.get("n_nodes")),
            n_cells=_coerce_optional_int(payload.get("n_cells")),
            constraints_mode=_optional_text(payload.get("constraints_mode")),
            source_mesh_path=_optional_text(payload.get("source_mesh_path")),
            files=CatchmentMeshBundleFilesView.from_mapping(payload.get("files")),
            geology=CatchmentMeshBundleGeologyView.from_mapping(payload.get("geology")),
            topography=CatchmentMeshBundleTopographyView.from_mapping(payload.get("topography")),
            vertical=CatchmentMeshBundleVerticalView.from_mapping(payload.get("vertical")),
            hydraulic_properties=CatchmentMeshBundleHydraulicPropertiesView.from_mapping(
                payload.get("hydraulic_properties")
            ),
        )


@dataclass(frozen=True)
class CatchmentMeshBundle:
    """In-memory view of one self-contained bundle directory.

    The object deliberately stays simple: it mirrors the exported CSV/JSON
    files so downstream scripts can inspect the bundle without importing the
    full HydroModPy mesh stack.
    """

    bundle_dir: Path
    metadata: dict[str, Any]
    nodes: tuple[CatchmentMeshBundleNode, ...]
    cells: tuple[CatchmentMeshBundleCell, ...]
    edges: tuple[CatchmentMeshBundleEdge, ...]
    geology_fractions: tuple[CatchmentMeshBundleGeologyFraction, ...]
    mesh_summary: dict[str, Any] | None = None

    @property
    def n_nodes(self) -> int:
        """Return the number of exported mesh nodes."""
        return int(len(self.nodes))

    @property
    def n_cells(self) -> int:
        """Return the number of exported 2D cells."""
        return int(len(self.cells))

    @property
    def n_edges(self) -> int:
        """Return the number of exported unique edges."""
        return int(len(self.edges))

    @property
    def mesh_path(self) -> Path:
        """Return the path of the copied `.msh` file inside the bundle."""
        filename = self.metadata_view.files.mesh
        return (self.bundle_dir / filename).resolve()

    @property
    def metadata_view(self) -> CatchmentMeshBundleMetadataView:
        """Return a typed convenience view over ``metadata.json``."""
        return CatchmentMeshBundleMetadataView.from_mapping(self.metadata)

    def node_coordinates(self) -> list[tuple[float, float]]:
        """Return planar node coordinates in bundle node order."""
        return [(float(node.x), float(node.y)) for node in self.nodes]

    def cell_connectivity(self) -> list[tuple[int, ...]]:
        """Return 2D cell connectivity using the exported zero-based node ids."""
        return [tuple(int(node_idx) for node_idx in cell.node_indices) for cell in self.cells]

    def cell_by_id(self, cell_id: int) -> CatchmentMeshBundleCell:
        """Return one cell by its exported `cell_id`."""
        target = int(cell_id)
        for cell in self.cells:
            if int(cell.cell_id) == target:
                return cell
        raise KeyError(f"Unknown cell_id={target}")


def _load_csv_rows(path: Path) -> list[dict[str, str]]:
    """Read one bundle CSV file as a list of raw string dictionaries."""
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        return [dict(row) for row in reader]


def _optional_text(raw_value: object) -> str | None:
    """Return one stripped string or ``None`` when empty."""
    if raw_value is None:
        return None
    text = str(raw_value).strip()
    return None if text == "" else text


def _coerce_optional_int(raw_value: object) -> int | None:
    """Parse one optional integer from loose JSON metadata values."""
    if raw_value is None:
        return None
    return int(str(raw_value).strip())


def _load_nodes(path: Path) -> tuple[CatchmentMeshBundleNode, ...]:
    """Load the `nodes.csv` table."""
    rows = _load_csv_rows(path)
    return tuple(
        CatchmentMeshBundleNode(
            node_id=int(row["node_id"]),
            x=float(row["x"]),
            y=float(row["y"]),
            z_top=_parse_optional_float(row.get("z_top", "")),
            z_bottom=_parse_optional_float(row.get("z_bottom", "")),
        )
        for row in rows
    )


def _read_cell_node_indices(row: dict[str, str]) -> tuple[int, ...]:
    """Read one cell's node list, honoring ``ncvert`` or scanning ``n<k>``.

    New bundles declare the real node count in ``ncvert`` (variable arity). Old
    bundles only carry the fixed ``n0..n3`` columns, so the fallback scans every
    present ``n<k>`` column in order and skips the empty padding slots.
    """
    ncvert_raw = str(row.get("ncvert", "")).strip()
    if ncvert_raw != "":
        count = int(ncvert_raw)
        return tuple(int(row[f"n{position}"]) for position in range(count))
    indices: list[int] = []
    position = 0
    while f"n{position}" in row:
        value = str(row.get(f"n{position}", "")).strip()
        if value != "":
            indices.append(int(value))
        position += 1
    return tuple(indices)


def _load_cells(path: Path) -> tuple[CatchmentMeshBundleCell, ...]:
    """Load the `cells.csv` table."""
    rows = _load_csv_rows(path)
    out: list[CatchmentMeshBundleCell] = []
    for row in rows:
        node_indices = _read_cell_node_indices(row)
        out.append(
            CatchmentMeshBundleCell(
                cell_id=int(row["cell_id"]),
                geom_type=str(row["geom_type"]),
                node_indices=node_indices,
                centroid_x=float(row["centroid_x"]),
                centroid_y=float(row["centroid_y"]),
                area_m2=float(row["area_m2"]),
                z_top_centroid=_parse_optional_float(row.get("z_top_centroid", "")),
                z_top_mean=_parse_optional_float(row.get("z_top_mean", "")),
                z_bottom_centroid=_parse_optional_float(row.get("z_bottom_centroid", "")),
                z_bottom_mean=_parse_optional_float(row.get("z_bottom_mean", "")),
                geology_code=_parse_optional_int(row.get("geology_code", "")),
                geology_key=str(row.get("geology_key", "")),
                hydraulic_conductivity_m_s=_parse_optional_float(
                    row.get("hydraulic_conductivity_m_s", "")
                ),
                storage_coefficient=_parse_optional_float(row.get("storage_coefficient", "")),
            )
        )
    return tuple(out)


def _load_edges(path: Path) -> tuple[CatchmentMeshBundleEdge, ...]:
    """Load the `edges.csv` table."""
    rows = _load_csv_rows(path)
    return tuple(
        CatchmentMeshBundleEdge(
            edge_id=int(row["edge_id"]),
            node_a=int(row["node_a"]),
            node_b=int(row["node_b"]),
            cell_a=int(row["cell_a"]),
            cell_b=_parse_optional_int(row.get("cell_b", "")),
            length_m=float(row["length_m"]),
            edge_kind=str(row["edge_kind"]),
            is_river=_parse_bool(row.get("is_river", "")),
            geology_a_key=str(row.get("geology_a_key", "")),
            geology_b_key=str(row.get("geology_b_key", "")),
        )
        for row in rows
    )


def _load_geology_fractions(path: Path) -> tuple[CatchmentMeshBundleGeologyFraction, ...]:
    """Load the optional per-cell geology fractions table."""
    rows = _load_csv_rows(path)
    return tuple(
        CatchmentMeshBundleGeologyFraction(
            cell_id=int(row["cell_id"]),
            geology_key=str(row["geology_key"]),
            fraction=float(row["fraction"]),
        )
        for row in rows
    )


def load_catchment_mesh_bundle(bundle_dir: str | Path) -> CatchmentMeshBundle:
    """Load one previously exported catchment mesh bundle.

    The loader is intentionally conservative: missing metadata is an error,
    while optional CSV companions simply become empty tuples.
    """
    bundle_path = Path(bundle_dir).resolve()
    metadata_path = bundle_path / "metadata.json"
    if not metadata_path.exists():
        raise FileNotFoundError(f"Bundle metadata not found: {metadata_path}")

    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    summary_path = bundle_path / "mesh_summary.json"
    mesh_summary = None
    if summary_path.exists():
        mesh_summary = json.loads(summary_path.read_text(encoding="utf-8"))

    return CatchmentMeshBundle(
        bundle_dir=bundle_path,
        metadata=dict(metadata),
        nodes=_load_nodes(bundle_path / "nodes.csv"),
        cells=_load_cells(bundle_path / "cells.csv"),
        edges=_load_edges(bundle_path / "edges.csv"),
        geology_fractions=_load_geology_fractions(bundle_path / "cell_geology_fractions.csv"),
        mesh_summary=mesh_summary,
    )


_ENGINE_VERSION = "1.0.0"


def cell_mesh_from_bundle(bundle: CatchmentMeshBundle, *, crs_wkt: str) -> PlanarCellMesh:
    """Read a bundle of triangles as a cell mesh.

    Cell and vertex ``i`` are the ``i``-th cell and node of the bundle. A face
    keeps the orientation of its bundle edge: ``cell_a`` is the cell the edge
    lists first, ``cell_b`` the other cell or -1.
    """
    node_position = {int(node.node_id): index for index, node in enumerate(bundle.nodes)}
    cell_position = {int(cell.cell_id): index for index, cell in enumerate(bundle.cells)}
    vertices = np.asarray([[node.x, node.y] for node in bundle.nodes], dtype=np.float64)
    arity = {len(cell.node_indices) for cell in bundle.cells}
    if arity != {3}:
        raise ValueError(
            f"a bundle cell mesh needs triangles; the cells have {sorted(arity)} nodes"
        )
    connectivity = np.asarray(
        [[node_position[int(node)] for node in cell.node_indices] for cell in bundle.cells],
        dtype=np.int64,
    )
    mesh = HydroMesh(
        vertices=vertices,
        cell_blocks=(CellBlock(cell_type=CellType.TRIANGLE, connectivity=connectivity),),
    )
    return build_planar_cell_mesh(
        mesh,
        vertices[connectivity].mean(axis=1),
        center_kind="vertex_mean",
        crs_wkt=crs_wkt,
        identity=MeshIdentity("triangle", _ENGINE_VERSION, "", None),
        declarations={
            "graded": True,
            "exact_faces": True,
            "deterministic": False,
            "needs_cache": True,
        },
        face_families=_face_families(bundle, node_position, cell_position, vertices),
    )


def _face_families(
    bundle: CatchmentMeshBundle,
    node_position: dict[int, int],
    cell_position: dict[int, int],
    vertices: np.ndarray,
) -> FaceFamilyTable | None:
    """Return the river faces and the faces of each outer side, or ``None`` when there is none."""
    edges = bundle.edges
    node_a = np.asarray([node_position[int(edge.node_a)] for edge in edges], dtype=np.int64)
    node_b = np.asarray([node_position[int(edge.node_b)] for edge in edges], dtype=np.int64)
    cell_a = np.asarray([cell_position[int(edge.cell_a)] for edge in edges], dtype=np.int64)
    cell_b = np.asarray(
        [-1 if edge.cell_b is None else cell_position[int(edge.cell_b)] for edge in edges],
        dtype=np.int64,
    )
    side_of_edge = np.where(cell_b < 0, box_side_of_edges(vertices, node_a, node_b), -1)

    selections = {"rivers": np.flatnonzero([edge.is_river for edge in edges])}
    for side in sorted(BOX_SIDES):
        selections[f"boundary:{side}"] = np.flatnonzero(side_of_edge == BOX_SIDES.index(side))
    selections = {name: rows for name, rows in selections.items() if rows.size}
    if not selections:
        return None
    return FaceFamilyTable.stack(
        [
            (
                name,
                {
                    "cell_a": cell_a[rows],
                    "cell_b": cell_b[rows],
                    "node_a": node_a[rows],
                    "node_b": node_b[rows],
                },
            )
            for name, rows in selections.items()
        ]
    )


__all__ = [
    "BUNDLE_COLUMNS",
    "BUNDLE_SCHEMA_VERSION",
    "CatchmentMeshBundle",
    "CatchmentMeshBundleCell",
    "CatchmentMeshBundleEdge",
    "CatchmentMeshBundleGeologyFraction",
    "CatchmentMeshBundleNode",
    "cell_mesh_from_bundle",
    "load_catchment_mesh_bundle",
]
