"""The earlier run a configuration reads, named by its ``sim_id``.

Why
---
Two keys of a configuration point at another run of the project: ``[flow]
restart_from`` and the ``run`` of a ``[[mesh.refinement_zone]]``. Both take a
run name, and a bare name is the latest version of that run. The frozen
``config.toml`` of a run writes the ``sim_id`` instead, so a replay reads the
very run the first attempt read. The run identity hash reads these keys
through their ``sim_id``, so the original configuration and its frozen copy
hash alike, and two runs that read two versions of one source run do not.

What a reference may be
-----------------------
A path to a field store or to a run directory (absolute, or relative to the
project root), a run name with or without its ``.vN``, a ``sim_id`` or an
unambiguous prefix of one (eight characters at least), or the table
``{sim_id, path}`` a frozen ``config.toml`` writes for ``restart_from``. A
reference that names no sealed run has no ``sim_id`` and stays as written.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hydromodpy.core.state.paths import runs_dir_for
from hydromodpy.results.manifest import is_sealed, read_manifest
from hydromodpy.results.storage.attempt import run_dir_for_name
from hydromodpy.results.storage.contract import FIELDS_STORE_NAME
from hydromodpy.results.storage.json_io import readable

__all__ = ["resolve_source_runs", "source_run_id"]

_MIN_PREFIX = 8
"""Shortest prefix of a ``sim_id`` that names a run."""


def source_run_id(project_root: Path, reference: str) -> str | None:
    """Return the ``sim_id`` of the sealed run *reference* names, or None.

    None when nothing under the project matches, when the run is not sealed,
    or when a prefix matches several runs.
    """
    text = reference.strip()
    if not text:
        return None
    root = Path(project_root)
    as_path = Path(text).expanduser()
    candidate = as_path if as_path.is_absolute() else root / as_path
    if candidate.exists():
        return _sealed_id(_run_dir_of(candidate))
    run_dir = run_dir_for_name(root, text)
    if run_dir is not None:
        return _sealed_id(run_dir)
    return _id_by_prefix(root, text)


def resolve_source_runs(payload: dict[str, Any], project_root: Path) -> None:
    """Write the ``sim_id`` of each source run in place of its reference, in *payload*.

    *payload* is a configuration as a dict. The ``run`` of every
    ``[[mesh.refinement_zone]]`` and ``[flow] restart_from`` are read. A
    reference that resolves to no sealed run is left as written.
    """
    mesh = payload.get("mesh")
    zones = mesh.get("refinement_zone") if isinstance(mesh, dict) else None
    for zone in zones if isinstance(zones, list) else ():
        if isinstance(zone, dict) and isinstance(zone.get("run"), str):
            zone["run"] = source_run_id(project_root, zone["run"]) or zone["run"]
    flow = payload.get("flow")
    reference = flow.get("restart_from") if isinstance(flow, dict) else None
    if isinstance(reference, str):
        flow["restart_from"] = source_run_id(project_root, reference) or reference
    elif isinstance(reference, dict):
        path = reference.get("path")
        sim_id = reference.get("sim_id") or (
            source_run_id(project_root, path) if isinstance(path, str) else None
        )
        if sim_id:
            flow["restart_from"] = str(sim_id)


def _run_dir_of(path: Path) -> Path:
    """The run directory a field store, a run directory or a file of it stands for."""
    if path.name == FIELDS_STORE_NAME:
        return path.parent
    return path if path.is_dir() else path.parent


def _sealed_id(run_dir: Path) -> str | None:
    if not is_sealed(run_dir):
        return None
    # A seal that cannot be read names no run: the reference stays as written.
    manifest = readable(read_manifest, run_dir)
    sim_id = None if manifest is None else manifest.get("run", {}).get("sim_id")
    return None if sim_id is None else str(sim_id)


def _id_by_prefix(root: Path, prefix: str) -> str | None:
    runs = runs_dir_for(root)
    if len(prefix) < _MIN_PREFIX or not runs.is_dir():
        return None
    found = {
        sim_id
        for entry in sorted(runs.iterdir())
        if entry.is_dir() and (sim_id := _sealed_id(entry)) is not None
        if sim_id.startswith(prefix)
    }
    return found.pop() if len(found) == 1 else None
