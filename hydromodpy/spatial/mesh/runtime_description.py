"""What a catchment meshing left on disk, and the document that says so.

Gmsh is not reproducible run to run (see :mod:`hydromodpy.spatial.mesh.mesh_cache`
for the measured evidence), so a step that re-meshes instead of reloading does
not repeat its work - it produces a *different* mesh, and every number computed
on it moves. A resume therefore has to read the mesh back, and reading it back
needs the runtime summary, which until now only ever existed in memory.

``setup.mesh_summary`` is already exactly the document
``load_mesh_artifacts_from_summary`` consumes, and it is strict JSON. This module
writes it next to the mesh it describes and reads it back.

The declaration covers **every file a rebuild of the step reads** - the mesh and
the exchange bundle - so a digest over it changes exactly when what a resume
would reuse changes. The QA sidecar the meshing writes beside the mesh is left
out on purpose: nothing reloads it.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

from hydromodpy.core.logging import get_logger

logger = get_logger(__name__)

DESCRIPTION_FILENAME = "_mesh_runtime_manifest.json"
SCHEMA_VERSION = "hydromodpy.mesh_runtime.v1"

# The summary keys naming a file the mesh directory holds. They are stored
# relative to that directory so the description describes the tree it sits in
# and not the machine that built it: a project copied elsewhere, keeping the
# original, would otherwise read the original's mesh forever. A path outside
# the directory - an external mesh named by ``[mesh_input]`` - stays absolute.
_PATH_KEYS = ("output_mesh", "output_exchange_bundle_dir", "output_summary_json")


def mesh_description_path(mesh_dir: Path) -> Path:
    """Return the description path inside a mesh output directory."""
    return Path(mesh_dir) / DESCRIPTION_FILENAME


def _stored_path(value: object, mesh_dir: Path) -> str:
    """Return a path as the document stores it: relative when inside ``mesh_dir``."""
    path = Path(str(value))
    try:
        return str(path.relative_to(mesh_dir))
    except ValueError:
        return str(path)


def _resolved_path(value: object, mesh_dir: Path) -> str:
    """Return a stored path as the runtime uses it, anchored on ``mesh_dir``."""
    path = Path(str(value))
    return str(path if path.is_absolute() else mesh_dir / path)


def _rewrite_paths(summary: dict[str, object], mesh_dir: Path, rewrite) -> dict[str, object]:
    """Return ``summary`` with its file-naming keys passed through ``rewrite``."""
    out = dict(summary)
    for key in _PATH_KEYS:
        raw = out.get(key)
        if isinstance(raw, str) and raw.strip() != "":
            out[key] = rewrite(raw, mesh_dir)
    return out


def write_mesh_description(mesh_dir: Path, summary: Mapping[str, object]) -> Path | None:
    """Describe the mesh just generated, next to the mesh itself.

    Written whatever ``[mesh_catchment] cache`` says: that flag decides whether
    a fresh run reuses a mesh some other run left, and says nothing about
    whether the mesh describes itself. Best-effort - a mesh that cannot be
    described is still a usable mesh for the process that holds it in memory.

    The write is atomic: a description truncated by a crash would be read back
    as a miss at best, and the reader would rather find nothing than a document
    it has to guess about.
    """
    mesh_dir = Path(mesh_dir)
    path = mesh_description_path(mesh_dir)
    payload = {
        "schema": SCHEMA_VERSION,
        "mesh_summary": _rewrite_paths(dict(summary), mesh_dir, _stored_path),
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(payload, indent=2, ensure_ascii=True, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        tmp.replace(path)
    except (OSError, TypeError, ValueError) as exc:
        logger.warning("mesh.description_write_failed dir=%s err=%s", mesh_dir, exc)
        return None
    return path


def read_mesh_description(mesh_dir: Path) -> dict[str, object] | None:
    """Return the runtime summary a previous meshing wrote, or None.

    A missing document, another schema version, or a summary naming a mesh that
    is no longer on disk are all a clean miss: the caller re-meshes, which is
    what it would have done anyway.

    Paths the document stores relative to the mesh directory are anchored on
    the directory the document was found in, never on the one that wrote it.
    """
    mesh_dir = Path(mesh_dir)
    path = mesh_description_path(mesh_dir)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning("mesh.description_unreadable path=%s err=%s", path, exc)
        return None
    if not isinstance(payload, dict) or payload.get("schema") != SCHEMA_VERSION:
        return None
    summary = payload.get("mesh_summary")
    if not isinstance(summary, dict):
        return None
    summary = _rewrite_paths(summary, mesh_dir, _resolved_path)
    mesh_path = str(summary.get("output_mesh", "")).strip()
    if mesh_path != "" and not Path(mesh_path).exists():
        logger.debug("mesh.description_names_a_missing_mesh path=%s", mesh_path)
        return None
    return summary


def mesh_artifact_paths(
    summary: Mapping[str, object] | None,
    mesh_dir: Path | None,
) -> tuple[Path, ...]:
    """Return every file a rebuild of the meshing step reads.

    Description first when it exists: it is what tells a later process that the
    mesh beside it is complete and which configuration produced it.
    """
    if not isinstance(summary, Mapping):
        return ()

    found: list[Path] = []
    if mesh_dir is not None:
        description = mesh_description_path(mesh_dir)
        if description.is_file():
            found.append(description)

    mesh_path = str(summary.get("output_mesh", "")).strip()
    if mesh_path != "" and (mesh_file := Path(mesh_path)).is_file():
        found.append(mesh_file)

    bundle_dir = str(summary.get("output_exchange_bundle_dir", "")).strip()
    if bundle_dir != "" and (bundle := Path(bundle_dir)).is_dir():
        found.extend(sorted(item for item in bundle.rglob("*") if item.is_file()))

    return tuple(found)


__all__ = (
    "DESCRIPTION_FILENAME",
    "SCHEMA_VERSION",
    "mesh_artifact_paths",
    "mesh_description_path",
    "read_mesh_description",
    "write_mesh_description",
)
