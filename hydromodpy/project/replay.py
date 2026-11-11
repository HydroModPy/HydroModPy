"""Replay a sealed run or a published copy: ``hmp replay REF``.

Why
---
A run is sealed with the values it computed and the inputs it read. Playing it
again on the same bytes is the only way to tell a code that still reproduces
its numbers from one that does not. The verb reads the ``config.toml`` of the
source, migrates it under today's names and defaults, pins every input at the
digest the source recorded, plays one run of the same stem as a new version,
and lets the seal class what the numbers did
(:mod:`hydromodpy.results.record.replay_class`).

What it refuses
---------------
A directory with no seal, a run without ``inputs.json``, a configuration the
migration refuses, and an input whose bytes moved. A published copy is read
from its own ``inputs/``, checked against its install index, and replays into
the project *base* names. The files a provider delivered are installed by their
digest in the workspace of that project first.

What it records
---------------
The class of the replay, its basis and the build drift enter the lineage of the
new run. A moved default or another solver binary is recorded and warned about,
never refused; ``strict`` refuses a value that did not reproduce the source,
before the seal, and leaves the attempt with its fields and no seal.
"""

from __future__ import annotations

import shutil
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from hydromodpy.config.config_migration import migrate_sealed_config_doc
from hydromodpy.core.exceptions import ConfigError
from hydromodpy.results.record.manifest import read_seal
from hydromodpy.results.storage.contract import (
    PUBLICATION_FILENAME,
    RUN_CONFIG_FILENAME,
    RUN_INPUTS_FILENAME,
    RUN_MANIFEST_FILENAME,
    RUN_RESOLVED_CONFIG_FILENAME,
)

if TYPE_CHECKING:
    from hydromodpy.project.environment import Environment
    from hydromodpy.results.run import Run


@dataclass(frozen=True, slots=True)
class ReplayTarget:
    """The sealed directory a replay reads, and the project it writes into."""

    source: Path
    project_root: Path


def replay_target(ref: str | Path, *, base: Path | None = None) -> ReplayTarget:
    """Return what *ref* names: the sealed directory and the project that receives the replay.

    *ref* is a run directory, its ``config.toml``, a published copy, or a bare
    run name under ``runs/`` of *base*. Without *base*, the project is the one
    above a run directory; a copy may sit outside any project and then needs one.
    """
    source = _sealed_source(ref, base)
    return ReplayTarget(source=source, project_root=_project_root_for(source, base))


def replay(
    ref: str | Path,
    *,
    strict: bool = False,
    base: Path | None = None,
    environment: Environment | None = None,
) -> Run:
    """Play the run sealed at *ref* again, class it, and return the new run.

    *ref* is a run directory, its ``config.toml``, or a published copy. *base*
    is the project the replay writes into: the project above a run directory
    when not given, and required for a copy, which may sit outside any project.
    *strict* refuses a deviation of the values before the seal. *environment*
    is the bounds of the call, as every file verb takes one.
    """
    from hydromodpy.project.dispatch.workflow import completed_run_view, run_simulation
    from hydromodpy.project.exchange.replay import replay_payload
    from hydromodpy.project.request import RunRequest
    from hydromodpy.workflow.replay_checks import check_replay_inputs

    target = replay_target(ref, base=base)
    source, project_root = target.source, target.project_root
    seal = read_seal(source)
    document = _document_of(source)
    if _is_copy(source):
        outcome = _play_copy(
            source,
            document,
            project_root=project_root,
            environment=environment,
            strict=strict,
            payload=replay_payload,
        )
    else:
        check_replay_inputs(source, project_root=project_root)
        request = RunRequest(config=document, name=seal.run.name_stem)
        outcome = run_simulation(
            request,
            base=project_root,
            environment=environment,
            replay_of=source,
            strict=strict,
        )
    if outcome is None:
        raise ConfigError(
            f"The replay of {source.name} owned no run directory, so nothing was sealed."
        )
    run = completed_run_view(outcome)
    if run is None:
        raise ConfigError(
            f"The replay of {source.name} wrote no readable record at {outcome.run_dir}."
        )
    return run


def _is_copy(source: Path) -> bool:
    """Whether *source* is a published copy rather than a run directory."""
    return (source / PUBLICATION_FILENAME).is_file()


def _sealed_source(ref: str | Path, base: Path | None = None) -> Path:
    """Return the sealed directory *ref* names, refusing one that holds no seal."""
    path = Path(ref).expanduser()
    if not path.exists():
        candidate = None if base is None else Path(base).expanduser().resolve() / "runs" / path
        if candidate is None or not candidate.exists():
            raise ConfigError(
                f"{candidate if candidate is not None else path.resolve()} does not exist: "
                "'hmp replay' reads a run directory, its config.toml, or a published copy."
            )
        path = candidate
    folder = path.resolve() if path.is_dir() else path.resolve().parent
    if _is_copy(folder):
        if not (folder / RUN_MANIFEST_FILENAME).is_file():
            raise ConfigError(
                f"{folder} carries {PUBLICATION_FILENAME} and no {RUN_MANIFEST_FILENAME}: "
                "a published copy holds both."
            )
        return folder
    if not (folder / RUN_MANIFEST_FILENAME).is_file():
        raise ConfigError(
            f"{folder} carries no seal, so it is no finished run. 'hmp replay' reads the "
            f"directory of a run with {RUN_MANIFEST_FILENAME}, or a published copy."
        )
    if not (folder / RUN_INPUTS_FILENAME).is_file():
        raise ConfigError(
            f"{folder} holds no {RUN_INPUTS_FILENAME}, so its inputs cannot be pinned: "
            "it is no run this code sealed."
        )
    return folder


def _project_root_for(source: Path, base: Path | None) -> Path:
    """Return the project a replay writes into, from *base* or from the run layout."""
    if base is not None:
        return Path(base).expanduser().resolve()
    if _is_copy(source):
        raise ConfigError(
            f"{source} is a published copy, which replays into a project: name the project "
            "with base= or -w."
        )
    if source.parent.name == "runs":
        return source.parent.parent.resolve()
    raise ConfigError(
        f"{source} does not sit under runs/ of a project, so the project it replays into "
        "cannot be found above it: name it with base= or -w."
    )


def _document_of(source: Path) -> dict[str, Any]:
    """Return the configuration of *source*, under today's names and defaults."""
    config = source / RUN_CONFIG_FILENAME
    if not config.is_file():
        raise ConfigError(
            f"{source} holds no {RUN_CONFIG_FILENAME}: a replay reads the configuration "
            "the run sealed."
        )
    document = tomllib.loads(config.read_text(encoding="utf-8"))
    edition = _sealed_edition(source)
    if edition is not None:
        document.setdefault("edition", edition)
    migrate_sealed_config_doc(document)
    return document


def _sealed_edition(source: Path) -> str | None:
    """Return the edition the resolved configuration of *source* names, or None.

    A ``config.toml`` written before a sealed run wrote its edition is read with
    the defaults of the edition the run computed under.
    """
    resolved = source / RUN_RESOLVED_CONFIG_FILENAME
    if not resolved.is_file():
        return None
    payload = tomllib.loads(resolved.read_text(encoding="utf-8"))
    edition = payload.get("edition")
    return None if edition is None else str(edition)


def _play_copy(
    source: Path,
    document: dict[str, Any],
    *,
    project_root: Path,
    environment: Environment | None,
    strict: bool,
    payload: Any,
) -> Any:
    """Play a published copy from the bytes under ``inputs/``, and clean the rebuilt folders."""
    from hydromodpy.project.dispatch.workflow import run_simulation
    from hydromodpy.project.request import RunRequest

    folder = project_root / ".hmp" / "replay"
    workdir = folder / source.name
    try:
        pointed = payload(source, document, workdir=workdir, project_root=project_root)
        request = RunRequest(config=pointed, name=read_seal(source).run.name_stem)
        return run_simulation(
            request,
            base=project_root,
            environment=environment,
            replay_of=source,
            strict=strict,
        )
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
        if folder.is_dir() and not any(folder.iterdir()):
            folder.rmdir()


__all__ = ["ReplayTarget", "replay", "replay_target"]
