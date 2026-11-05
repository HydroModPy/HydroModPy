"""``[flow] restart_from`` by reference: a run name, a ``sim_id`` or a path.

Why
---
A hotstart names the run whose last heads seed this one. Naming it by path
ties the configuration to one checkout; naming it by run keeps the link by
id (D3): the frozen ``config.toml`` writes the path relative to the project
and the lineage of the run records the ``sim_id`` of its source. The
reference is resolved here, at execution, before the solver builder reads a
path.

What a reference may be
-----------------------
- a path to a field store or to a run directory, absolute or relative to the
  project root;
- a run name, with or without its ``.vN`` (the latest version without);
- the ``sim_id`` of a sealed run, or an unambiguous prefix of it;
- the table ``{sim_id, path}`` a frozen ``config.toml`` writes
  (:class:`~hydromodpy.physics.flow.flow_config.RestartReference`): the
  ``sim_id`` is looked up first, among the runs of this project, then the
  ``path``, so a replay in another project still finds its store.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from hydromodpy.core.exceptions import ConfigError
from hydromodpy.core.state.layout import runs_dir_for
from hydromodpy.core.state.result_dirs import run_dir_rel
from hydromodpy.physics.flow.flow_config import RestartReference
from hydromodpy.results.manifest import is_sealed, read_manifest
from hydromodpy.results.storage.attempt import run_dir_for_name
from hydromodpy.results.storage.contract import FIELDS_STORE_NAME
from hydromodpy.results.storage.json_io import readable


@dataclass(frozen=True, slots=True)
class RestartSource:
    """The run a hotstart reads, by id and by path."""

    sim_id: str | None
    """Id of the sealed run the store belongs to; None for a store outside any seal."""

    path: Path
    """The field store the solver reads."""

    rel_dir: str | None
    """``runs/<name>`` of the source run, for the lineage hint."""


def resolve_restart_source(project_root: Path, reference: str | RestartReference) -> RestartSource:
    """Return the store a ``restart_from`` reference names.

    Raises :class:`~hydromodpy.core.exceptions.ConfigError` when nothing under
    the project matches the reference.
    """
    root = Path(project_root)
    if isinstance(reference, RestartReference):
        return _from_reference(root, reference)
    text = str(reference).strip()
    if not text:
        raise ConfigError("flow.restart_from is empty: name a run or a field store.")
    as_path = Path(text).expanduser()
    candidate = as_path if as_path.is_absolute() else root / as_path
    if candidate.exists():
        return _from_path(candidate)
    run_dir = run_dir_for_name(root, text) or _run_dir_by_sim_id(root, text)
    if run_dir is None:
        raise ConfigError(
            f"flow.restart_from = {text!r} names no field store, no run under "
            f"{runs_dir_for(root)} and no sealed sim_id of this project."
        )
    store = run_dir / FIELDS_STORE_NAME
    if not store.is_dir():
        raise ConfigError(
            f"flow.restart_from = {text!r}: {run_dir.name} has no {FIELDS_STORE_NAME}."
        )
    return RestartSource(sim_id=_sim_id_of(run_dir), path=store, rel_dir=run_dir_rel(run_dir.name))


def _from_reference(root: Path, reference: RestartReference) -> RestartSource:
    """The table form: the ``sim_id`` among the runs of the project, else the ``path``."""
    if reference.sim_id:
        run_dir = _run_dir_by_sim_id(root, reference.sim_id)
        if run_dir is not None and (run_dir / FIELDS_STORE_NAME).is_dir():
            return RestartSource(
                sim_id=_sim_id_of(run_dir),
                path=run_dir / FIELDS_STORE_NAME,
                rel_dir=run_dir_rel(run_dir.name),
            )
    if reference.path:
        as_path = Path(reference.path).expanduser()
        candidate = as_path if as_path.is_absolute() else root / as_path
        if candidate.exists():
            found = _from_path(candidate)
            return RestartSource(
                sim_id=found.sim_id or reference.sim_id, path=found.path, rel_dir=found.rel_dir
            )
    raise ConfigError(
        f"flow.restart_from = {{sim_id = {reference.sim_id!r}, path = {reference.path!r}}}: no "
        f"sealed run of this project has that sim_id and the path names no field store under "
        f"{root}."
    )


def _from_path(path: Path) -> RestartSource:
    """A path names a store, or a run directory whose store is read."""
    store = (
        path / FIELDS_STORE_NAME if path.is_dir() and (path / FIELDS_STORE_NAME).is_dir() else path
    )
    run_dir = store.parent
    if is_sealed(run_dir):
        return RestartSource(
            sim_id=_sim_id_of(run_dir), path=store, rel_dir=run_dir_rel(run_dir.name)
        )
    return RestartSource(sim_id=None, path=store, rel_dir=None)


def _run_dir_by_sim_id(root: Path, prefix: str) -> Path | None:
    runs = runs_dir_for(root)
    if not runs.is_dir() or len(prefix) < 8:
        return None
    matches = [
        entry
        for entry in sorted(runs.iterdir())
        if entry.is_dir() and (sid := _sim_id_of(entry)) is not None and sid.startswith(prefix)
    ]
    if len(matches) > 1:
        names = ", ".join(entry.name for entry in matches)
        raise ConfigError(f"flow.restart_from = {prefix!r} matches several runs: {names}.")
    return matches[0] if matches else None


def _sim_id_of(run_dir: Path) -> str | None:
    if not is_sealed(run_dir):
        return None
    manifest = readable(read_manifest, run_dir)
    sim_id = None if manifest is None else manifest.get("run", {}).get("sim_id")
    return None if sim_id is None else str(sim_id)


__all__ = ["RestartSource", "resolve_restart_source"]
