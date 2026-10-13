"""Cache of the meshes an engine cannot rebuild bit for bit.

Gmsh draws from the system clock, so a mesh generated twice from one request
differs. An engine that declares ``needs_cache`` is built once per request: the
mesh is stored under ``<project>/.hmp/mesh_cache/<key>/`` and every later run,
resume and ``restart_from`` of the project reads it back. The key names the
request, the engine and its version, and the gmsh build.

An entry is a directory holding ``mesh.npz`` (arrays) and ``mesh.json`` (the
rest). It is written in a temporary directory and renamed, so a reader sees a
complete entry or none, also when two runs of a project build the same mesh.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from importlib import metadata
from pathlib import Path

import numpy as np

from hydromodpy.core.exceptions import MeshError
from hydromodpy.spatial.mesh.model.hydro_mesh import CellBlock, HydroMesh
from hydromodpy.spatial.mesh.model.mesh_qa import MeshQA
from hydromodpy.spatial.mesh.model.planar_cell_mesh import (
    CellChain,
    FaceFamilyTable,
    MeshIdentity,
    PlanarCellMesh,
)
from hydromodpy.spatial.mesh.request import MeshRequest

__all__ = [
    "ARRAYS_FILENAME",
    "DESCRIPTION_FILENAME",
    "SCHEMA_VERSION",
    "cache_dir",
    "cache_key",
    "has_cell_mesh",
    "load_cell_mesh",
    "save_cell_mesh",
]

CACHE_SUBDIR = Path(".hmp") / "mesh_cache"
"""Where the entries live, under the project root."""

ARRAYS_FILENAME = "mesh.npz"
DESCRIPTION_FILENAME = "mesh.json"
SCHEMA_VERSION = "hydromodpy.mesh_cache.v1"

_FACE_COLUMNS = ("family", "cell_a", "cell_b", "node_a", "node_b", "zone_left", "zone_right")


def cache_key(request: MeshRequest, engine_cls: type) -> str:
    """Return the sha256 hex key of one request meshed by one engine build.

    The key reads the request hash, the engine id and version, and the version
    of gmsh, whose meshes change with it.
    """
    try:
        gmsh_version = metadata.version("gmsh")
    except metadata.PackageNotFoundError:
        gmsh_version = "absent"  # an engine that needs no gmsh keys on its absence
    digest = hashlib.sha256()
    for part in (
        SCHEMA_VERSION,
        request.canonical_hash(),
        engine_cls.engine_id,
        engine_cls.engine_version,
        gmsh_version,
    ):
        digest.update(part.encode())
        digest.update(b"\0")
    return digest.hexdigest()


def cache_dir(project_root: str | Path, key: str) -> Path:
    """Return the directory of the entry *key* under *project_root*."""
    return Path(project_root) / CACHE_SUBDIR / key


def has_cell_mesh(directory: str | Path) -> bool:
    """Whether *directory* holds a complete entry."""
    return (Path(directory) / DESCRIPTION_FILENAME).is_file()


def save_cell_mesh(cell_mesh: PlanarCellMesh, directory: str | Path) -> None:
    """Store *cell_mesh* in *directory*, unless a complete entry is already there."""
    target = Path(directory)
    if has_cell_mesh(target):
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = target.parent / f".{target.name}.{os.getpid()}.tmp"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir()
    try:
        arrays, description = _encode(cell_mesh)
        np.savez(staging / ARRAYS_FILENAME, **arrays)
        (staging / DESCRIPTION_FILENAME).write_text(json.dumps(description), encoding="utf-8")
        try:
            staging.rename(target)
        except OSError:
            if not has_cell_mesh(target):
                raise
            # A concurrent run stored the same entry first: its copy stands.
            shutil.rmtree(staging)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def load_cell_mesh(directory: str | Path) -> PlanarCellMesh:
    """Read back the mesh stored in *directory*.

    Raises
    ------
    MeshError
        When the entry is missing, of another schema, or unreadable.
    """
    source = Path(directory)
    if not has_cell_mesh(source):
        raise MeshError(f"No cached mesh in {source}.")
    try:
        description = json.loads((source / DESCRIPTION_FILENAME).read_text(encoding="utf-8"))
        with np.load(source / ARRAYS_FILENAME, allow_pickle=False) as stored:
            arrays = {name: stored[name] for name in stored.files}
    except (OSError, ValueError) as exc:
        raise MeshError(f"The cached mesh in {source} is unreadable: {exc}. Delete it.") from exc
    if description.get("schema") != SCHEMA_VERSION:
        raise MeshError(
            f"The cached mesh in {source} has schema {description.get('schema')!r}, "
            f"this build reads {SCHEMA_VERSION!r}. Delete it."
        )
    return _decode(arrays, description)


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
        connectivity=_block_connectivity(arrays["connectivity"], str(description["cell_type"])),
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
    qa = dict(description["qa"])
    qa["notes"] = tuple(qa["notes"])
    return PlanarCellMesh(
        mesh=mesh,
        centers=arrays["centers"],
        center_kind=description["center_kind"],
        crs_wkt=description["crs_wkt"],
        identity=MeshIdentity(**description["identity"]),
        qa=MeshQA(**qa),
        cell_chains=tuple(chains),
        face_families=table,
        cell_zone=arrays.get("cell_zone"),
        zone_names=tuple(description["zone_names"]),
        structured_shape=_shape_or_none(description["structured_shape"]),
    )


def _block_connectivity(rows: np.ndarray, cell_type: str) -> object:
    """Cell rows as the block holds them: ragged polygons drop their ``-1`` padding."""
    if cell_type != "polygon":
        return rows
    return tuple(row[row >= 0] for row in rows)


def _prefixed(arrays: dict[str, np.ndarray], prefix: str) -> dict[str, np.ndarray]:
    return {
        name[len(prefix) :]: values for name, values in arrays.items() if name.startswith(prefix)
    }


def _shape_or_none(shape: object) -> tuple[int, ...] | None:
    return None if shape is None else tuple(int(v) for v in shape)  # type: ignore[union-attr]
