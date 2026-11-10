"""The codec of the stored mesh product: ``write_mesh`` and ``read_mesh``.

A mesh an engine does not promise to rebuild bit for bit is stored once per
request, as ``mesh.npz`` (the arrays) and ``mesh.json`` (the rest). The product
store hands ``write_mesh`` an empty directory and renames it once complete, so
the codec holds no rename of its own. The format keeps the 2.0 identifier
``hydromodpy.mesh_cache.v1``, so an entry stored by 2.0 still reads. An entry
stored before the shape entries of the QA (bisection offset, corner angles,
concave cells) is read as it is: those entries are measured on the stored mesh
and centers, so the frozen mesh of a project survives without a new schema.
"""

from __future__ import annotations

import json
import zipfile
from importlib import metadata
from pathlib import Path

import numpy as np

from hydromodpy.core.exceptions import MeshError
from hydromodpy.mesh.planar.geometry import derive_geometry
from hydromodpy.mesh.planar.hydro_mesh import CellBlock, HydroMesh
from hydromodpy.mesh.planar.planar_cell_mesh import (
    CellChain,
    FaceFamilyTable,
    MeshIdentity,
    PlanarCellMesh,
)
from hydromodpy.mesh.planar.quality import SHAPE_KEYS, MeshQA, cell_shape_qa

__all__ = [
    "ARRAYS_FILENAME",
    "DESCRIPTION_FILENAME",
    "SCHEMA_VERSION",
    "library_versions",
    "read_mesh",
    "write_mesh",
]

ARRAYS_FILENAME = "mesh.npz"
DESCRIPTION_FILENAME = "mesh.json"
SCHEMA_VERSION = "hydromodpy.mesh_cache.v1"

_FACE_COLUMNS = ("family", "cell_a", "cell_b", "node_a", "node_b", "zone_left", "zone_right")


def library_versions() -> dict[str, str]:
    """Return the versions of the libraries a mesh depends on, by name.

    Shapely, the GEOS it wraps, scipy and gmsh: a new build of any of them can
    move a vertex, so each one is part of the product key and is stored with the
    mesh of a run. ``"absent"`` stands for an uninstalled gmsh, which an engine
    that needs none keys on.
    """
    import scipy
    import shapely

    try:
        gmsh_version = metadata.version("gmsh")
    except metadata.PackageNotFoundError:
        gmsh_version = "absent"
    return {
        "gmsh": gmsh_version,
        "scipy": scipy.__version__,
        "shapely": shapely.__version__,
        "geos": shapely.geos_version_string,
    }


def write_mesh(cell_mesh: PlanarCellMesh, directory: str | Path) -> None:
    """Write *cell_mesh* into *directory*, which the product store handed over empty."""
    target = Path(directory)
    target.mkdir(parents=True, exist_ok=True)
    arrays, description = _encode(cell_mesh)
    np.savez(target / ARRAYS_FILENAME, **arrays)
    (target / DESCRIPTION_FILENAME).write_text(json.dumps(description), encoding="utf-8")


def read_mesh(directory: str | Path) -> PlanarCellMesh:
    """Read back the mesh stored in *directory*.

    Raises
    ------
    MeshError
        When the entry is missing, of another schema, or unreadable.
    """
    source = Path(directory)
    if not (source / DESCRIPTION_FILENAME).is_file():
        raise MeshError(f"No stored mesh in {source}.")
    try:
        description = json.loads((source / DESCRIPTION_FILENAME).read_text(encoding="utf-8"))
        with np.load(source / ARRAYS_FILENAME, allow_pickle=False) as stored:
            arrays = {name: stored[name] for name in stored.files}
    except (OSError, ValueError, EOFError, zipfile.BadZipFile) as exc:
        raise MeshError(f"The stored mesh in {source} is unreadable: {exc}. Delete it.") from exc
    if description.get("schema") != SCHEMA_VERSION:
        raise MeshError(
            f"The stored mesh in {source} has schema {description.get('schema')!r}, "
            f"this build reads {SCHEMA_VERSION!r}. Delete it."
        )
    try:
        return _decode(arrays, description)
    except KeyError as exc:
        raise MeshError(f"The stored mesh in {source} lacks {exc}. Delete it.") from exc


def _encode(cell_mesh: PlanarCellMesh) -> tuple[dict[str, np.ndarray], dict[str, object]]:
    """Split a mesh into the arrays of the npz and the JSON description."""
    mesh = cell_mesh.mesh
    arrays: dict[str, np.ndarray] = {
        "vertices": mesh.vertices,
        "connectivity": np.asarray(cell_mesh.connectivity_rows),
        "centers": cell_mesh.centers,
    }
    for name, values in mesh.cell_data.items():
        arrays[f"cell_data/{name}"] = np.asarray(values)
    for name, values in mesh.point_data.items():
        arrays[f"point_data/{name}"] = np.asarray(values)
    chains = cell_mesh.cell_chains
    arrays["chain_id"] = np.asarray([chain.chain_id for chain in chains], dtype=np.int64)
    arrays["chain_length"] = np.asarray([chain.cell_ids.size for chain in chains], dtype=np.int64)
    arrays["chain_cells"] = (
        np.concatenate([chain.cell_ids for chain in chains])
        if chains
        else np.empty(0, dtype=np.int64)
    )
    table = cell_mesh.face_families
    if table is not None:
        for column in _FACE_COLUMNS:
            arrays[f"faces/{column}"] = getattr(table, column)
    if cell_mesh.cell_zone is not None:
        arrays["cell_zone"] = cell_mesh.cell_zone
    identity = cell_mesh.identity
    description: dict[str, object] = {
        "schema": SCHEMA_VERSION,
        "cell_type": mesh.cell_types[0].value,
        "mesh_structured_shape": _shape_or_none(mesh.structured_shape),
        "structured_shape": _shape_or_none(cell_mesh.structured_shape),
        "center_kind": cell_mesh.center_kind,
        "crs_wkt": cell_mesh.crs_wkt,
        "identity": {
            "engine_id": identity.engine_id,
            "engine_version": identity.engine_version,
            "request_hash": identity.request_hash,
            "seed": identity.seed,
        },
        "chain_families": [chain.family for chain in chains],
        "face_family_names": None if table is None else list(table.names),
        "zone_names": list(cell_mesh.zone_names),
        "qa": cell_mesh.qa.as_dict(),
    }
    return arrays, description


def _decode(arrays: dict[str, np.ndarray], description: dict[str, object]) -> PlanarCellMesh:
    """Rebuild a mesh from its arrays and description."""
    block = CellBlock(
        cell_type=str(description["cell_type"]),
        connectivity=arrays["connectivity"],
    )
    mesh = HydroMesh(
        vertices=arrays["vertices"],
        cell_blocks=(block,),
        cell_data=_prefixed(arrays, "cell_data/"),
        point_data=_prefixed(arrays, "point_data/"),
        structured_shape=_shape_or_none(description["mesh_structured_shape"]),
    )
    chains, offset = [], 0
    for family, chain_id, length in zip(
        description["chain_families"], arrays["chain_id"], arrays["chain_length"], strict=True
    ):
        chains.append(
            CellChain(family, int(chain_id), arrays["chain_cells"][offset : offset + int(length)])
        )
        offset += int(length)
    names = description["face_family_names"]
    table = (
        None
        if names is None
        else FaceFamilyTable(names=tuple(names), **{c: arrays[f"faces/{c}"] for c in _FACE_COLUMNS})
    )
    return PlanarCellMesh(
        mesh=mesh,
        centers=arrays["centers"],
        center_kind=description["center_kind"],
        crs_wkt=description["crs_wkt"],
        identity=MeshIdentity(**description["identity"]),
        qa=_decode_qa(description["qa"], mesh, arrays["centers"]),
        cell_chains=tuple(chains),
        face_families=table,
        cell_zone=arrays.get("cell_zone"),
        zone_names=tuple(description["zone_names"]),
        structured_shape=_shape_or_none(description["structured_shape"]),
    )


def _decode_qa(stored: dict[str, object], mesh: HydroMesh, centers: np.ndarray) -> MeshQA:
    """Rebuild the QA, measuring the shape entries an older entry lacks."""
    qa = dict(stored)
    qa["notes"] = tuple(qa["notes"])
    if any(name not in qa for name in SHAPE_KEYS):
        vertices = np.asarray(mesh.vertices, dtype=float)[:, :2]
        shape = cell_shape_qa(
            centers, vertices, derive_geometry(mesh), float(qa["min_face_length_m"])
        )
        qa = {**shape, **qa}
    return MeshQA(**qa)


def _prefixed(arrays: dict[str, np.ndarray], prefix: str) -> dict[str, np.ndarray]:
    return {
        name[len(prefix) :]: values for name, values in arrays.items() if name.startswith(prefix)
    }


def _shape_or_none(shape: object) -> tuple[int, ...] | None:
    return None if shape is None else tuple(int(v) for v in shape)  # type: ignore[union-attr]
