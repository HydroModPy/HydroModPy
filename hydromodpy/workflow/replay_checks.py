"""What a replay of a sealed run checks before it runs: its inputs, then its producer.

``hmp replay REF`` plays a sealed run again from its own record: the digests of
``inputs.json`` beside the file, and the pins the replay hands to the data step
so a provider cannot refresh a file under it. A digest that moved is refused
before anything runs (:class:`~hydromodpy.core.exceptions.FrozenDataError`).
What the build decided otherwise, and the provenance entries that differ, are
recorded in the lineage of the new run and never refused; only ``--strict``
refuses a moved value, and :mod:`hydromodpy.results.record.replay_class` does
that at the seal.

The module sits at the root of ``workflow`` and not in ``record/``, because it reads
``steps.prepare_solver.resolved`` and ``steps`` imports ``record``: inside ``record/``
it would close a cycle. A check at replay is a function of this module, and the checks
cover the inputs, the configuration and the solver binary.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from hydromodpy.core.exceptions import FrozenDataError
from hydromodpy.core.io.file_digest import sha256_of
from hydromodpy.core.logging import get_logger
from hydromodpy.core.state.portable import decode_workspace_path
from hydromodpy.core.workspace.resolve import locate_workspace_root
from hydromodpy.data.provenance.lockfile import (
    USER_FILE_SOURCE,
    LockedInput,
    LockedInputs,
    user_file_input,
)
from hydromodpy.results.record.manifest import KEY_PACKAGES, read_manifest, sealed_in_run
from hydromodpy.results.record.record import RunProvenance, read_inputs, read_provenance
from hydromodpy.results.storage.contract import (
    PUBLICATION_FILENAME,
    RUN_CONFIG_FILENAME,
    RUN_INPUTS_FILENAME,
    RUN_MANIFEST_FILENAME,
    RUN_RESOLVED_CONFIG_FILENAME,
)
from hydromodpy.results.storage.json_io import readable
from hydromodpy.schema.lineage import ProducerSide
from hydromodpy.workflow.steps.prepare_solver.resolved import compare_with_sealed

logger = get_logger(__name__)


def check_replay_inputs(run_dir: Path, *, project_root: Path) -> None:
    """Refuse a replay whose inputs are not the bytes the run read.

    Each file ``inputs.json`` records is looked for where the sealed run read
    it, and each entry the manifest lists as a folder is walked for the state of
    its rows. The first thing that is missing or has another digest refuses the
    replay, and the message names every such input with both digests.
    """
    lines = _input_mismatches(run_dir, project_root)
    if lines:
        raise FrozenDataError(
            f"hmp replay: {len(lines)} input(s) of {run_dir.name} differ from its record. "
            "Restore them, then replay again:\n  " + "\n  ".join(lines)
        )


def sealed_run_of(config_path: Path) -> Path | None:
    """Return the sealed run *config_path* is the frozen configuration of, or None."""
    path = Path(config_path).resolve()
    folder = path.parent
    if path.name != RUN_CONFIG_FILENAME:
        return None
    if (folder / RUN_MANIFEST_FILENAME).is_file() and (folder / RUN_INPUTS_FILENAME).is_file():
        return folder
    return None


REPLAYED_FILE_PROVIDERS = frozenset({"file", "url"})
"""The providers of ``inputs.json`` whose bytes the request id already holds."""

USER_FILE_PROVIDERS = frozenset({USER_FILE_SOURCE, "custom"})
"""The providers of ``inputs.json`` that name a file of the user."""


def api_inputs_intact(run_dir: Path, project_root: Path) -> bool:
    """Whether each file of an API the sealed run read is in the cache with the digest it recorded.

    A file of an API whose extent comes from the delineated catchment is fetched after
    the request id is told, so the id holds its declaration and not its bytes. A run is
    given back for an identical request only when each such file is still where the run
    read it, with the same sha256: a provider that refreshed it, or a cache that
    dropped it, leaves the request to compute again. A run whose ``inputs.json`` cannot
    be read is not intact. A file of the user or of a URL is covered by the request id
    and is not read here.
    """
    document = readable(read_inputs, run_dir)
    if document is None:
        return False
    root = Path(project_root).resolve()
    workspace = locate_workspace_root(root) or root
    for entry in document.inputs:
        if entry.provider in REPLAYED_FILE_PROVIDERS or not entry.path or not entry.sha256:
            continue
        if sealed_in_run(entry):
            continue
        located = decode_workspace_path(workspace, entry.path)
        if located.is_dir():
            continue
        if not located.is_file() or sha256_of(located) != entry.sha256:
            return False
    return True


def _recorded_inputs(run_dir: Path) -> dict[str, tuple[str, str, str]]:
    """Return ``{path: (name, sha256, provider)}`` of the files a run says it read.

    ``inputs.json`` comes first, then the manifest, which lists what the
    configuration declares, a folder among them. A path is relative to the
    workspace. The row of the sealed mesh leaves out: its bytes sit in ``mesh/``
    of the run itself, which the build step reads, not in the workspace.
    """
    recorded: dict[str, tuple[str, str, str]] = {
        str(entry.path): (str(entry.variable), str(entry.sha256), str(entry.provider))
        for entry in read_inputs(run_dir).inputs
        if entry.path and entry.sha256 and not sealed_in_run(entry)
    }
    for entry in read_manifest(run_dir).get("inputs") or ():
        path, digest = entry.get("path"), entry.get("sha256")
        if path and digest and str(path) not in recorded:
            recorded[str(path)] = (
                str(entry.get("role") or "input"),
                str(digest),
                str(entry.get("provider") or "input"),
            )
    return recorded


def _input_mismatches(run_dir: Path, project_root: Path) -> list[str]:
    """Return one line per recorded input that is missing or has another digest here.

    A declared folder only has to be there: the run read some files of it, which the
    record lists one by one, and a file added beside them is no other input. A URL
    whose file left the cache is no mismatch: the replay contacts it again, its
    bytes are not pinned, and values that move with them show in the class of the
    replay. The state a window
    starts from is compared by the digest of the state, not by that of a file.
    """
    from hydromodpy.workflow.steps.prepare_solver.restart import INITIAL_STATE_VARIABLE

    root = Path(project_root).resolve()
    workspace = locate_workspace_root(root) or root
    lines: list[str] = []
    recorded = _recorded_inputs(run_dir)
    for path, (name, sealed, provider) in sorted(recorded.items()):
        if name.split(":", 1)[0] == INITIAL_STATE_VARIABLE or name == INITIAL_STATE_VARIABLE:
            line = _initial_state_mismatch(path, name, sealed, root)
            if line is not None:
                lines.append(line)
            continue
        located = decode_workspace_path(workspace, path)
        if not located.exists():
            if provider != "url":
                lines.append(f"{name} ({path}): sealed {sealed}, missing from {located}")
            continue
        if located.is_dir():
            continue
        found = sha256_of(located)
        if found != sealed:
            lines.append(f"{name} ({path}): sealed {sealed}, found {found}")
    return lines


def _initial_state_mismatch(path: str, name: str, sealed: str, project_root: Path) -> str | None:
    """Return the line of a window state whose digest moved, or None when it holds."""
    from hydromodpy.results.record.request_identity import prior_state_digest
    from hydromodpy.results.storage.prior_state import prior_state_at

    folder = Path(path)
    run_folder = folder if folder.is_absolute() else project_root / folder
    if not run_folder.exists():
        return f"{name} ({path}): sealed {sealed}, missing from {run_folder}"
    try:
        found = prior_state_digest(prior_state_at(str(run_folder)))
    except (KeyError, OSError, TypeError, ValueError) as exc:
        return f"{name} ({path}): sealed {sealed}, the state there does not read ({exc})"
    if found != sealed:
        return f"{name} ({path}): sealed {sealed}, found {found}"
    return None


def locked_inputs_of(
    source_run: Path, *, project_root: Path, data_dir: Path
) -> LockedInputs | None:
    """Return the inputs a replay pins from ``inputs.json``, or None for a published copy.

    The records take the shape of a lockfile, so the data step finds each file
    and each row of the cache by the digest the sealed run recorded. A user file
    is pinned at its path under *project_root*; a cache row at its path under
    *data_dir*. A copy reads the bytes of its ``inputs/``, which the install
    index checks, and pins nothing.
    """
    source = Path(source_run)
    if (source / PUBLICATION_FILENAME).is_file():
        return None
    document = readable(read_inputs, source)
    if document is None:
        return None
    root = Path(project_root).resolve()
    data_root = Path(data_dir).resolve()
    workspace = locate_workspace_root(root) or root
    pins: list[LockedInput] = []
    for entry in document.inputs:
        if not entry.path or not entry.sha256 or sealed_in_run(entry):
            continue
        variable = str(entry.variable).split(":", 1)[0]
        located = decode_workspace_path(workspace, entry.path)
        if entry.provider in USER_FILE_PROVIDERS:
            pins.append(
                user_file_input(
                    located,
                    variable=variable,
                    project_root=root,
                    sha256=entry.sha256,
                    license=entry.license,
                )
            )
            continue
        if entry.provider == "url" or not located.is_file():
            continue
        try:
            relative = located.relative_to(data_root).as_posix()
        except ValueError:
            # A row of the user cache, outside the data folder of the project:
            # the bytes checked before the run still say what it reads.
            continue
        pins.append(
            LockedInput(
                variable=variable,
                source=str(entry.provider),
                station_id=_station_of(entry.request),
                product=entry.product,
                path=relative,
                sha256=entry.sha256,
                bytes=entry.bytes,
                license=entry.license,
                fetched_at="" if entry.fetched_at is None else entry.fetched_at.isoformat(),
            )
        )
    return LockedInputs(project_root=root, path=source / RUN_INPUTS_FILENAME, inputs=tuple(pins))


def _station_of(request: Mapping[str, Any]) -> str | None:
    """Return the station an input's request names, or None for a request that names none."""
    station = request.get("station")
    return None if station in (None, "") else str(station)


def warn_config_drift(
    config: Any, run_dir: Path | None, *, intended: Iterable[str] = ()
) -> dict[str, dict[str, Any]]:
    """Warn about each key a rerun or a replay takes otherwise than its source, and return them.

    The result is what ``lineage.drift`` records, with the keys the parent did not
    seal and the run holds at their default under ``new_at_default``. *intended*
    names what the caller asked to change.
    """
    if run_dir is None:
        return {}
    project_root = Path(config.workspace.project_root)
    compared = compare_with_sealed(config, run_dir, project_root=project_root, intended=intended)
    if compared is None:
        logger.warning(
            "%s holds no %s: this run cannot say whether a default moved since.",
            Path(run_dir).name,
            RUN_RESOLVED_CONFIG_FILENAME,
        )
        return {}
    for item in compared.drift:
        logger.warning("%s takes another value. %s", Path(run_dir).name, item.line())
    recorded: dict[str, dict[str, Any]] = {item.key: item.record() for item in compared.drift}
    if compared.new_at_default:
        recorded["new_at_default"] = dict(compared.new_at_default)
    return recorded


def producer_differences(source_run: Path, found: RunProvenance) -> dict[str, ProducerSide]:
    """Return the provenance entries that differ between *source_run* and *found*.

    *found* is the provenance the replay is about to write, built from its own
    facts before the seal. A replay is classified before its provenance is on
    disk, so the comparison is made here and the table enters
    ``lineage.replay.producer``.
    """
    sealed = _producer_facts(read_provenance(source_run))
    current = _producer_facts(found)
    return {
        key: ProducerSide(sealed=sealed.get(key), found=current.get(key))
        for key in sorted(set(sealed) | set(current))
        if sealed.get(key) != current.get(key)
    }


def _producer_facts(provenance: RunProvenance) -> dict[str, Any]:
    """Return the producer entries a replay compares, by their dotted path."""
    facts: dict[str, Any] = {
        "tool.version": provenance.tool.get("version"),
        "python.version": provenance.python.get("version"),
        "platform.platform": provenance.platform.get("platform"),
        "solver.version": provenance.solver.get("version"),
        "solver.binary_sha256": provenance.solver.get("binary_sha256"),
        "image.digest": (provenance.environment.get("image") or {}).get("digest"),
    }
    for name in KEY_PACKAGES:
        facts[f"packages.{name}"] = provenance.packages.get(name)
    return facts


def warn_producer_differences(source_run: Path, differences: Mapping[str, ProducerSide]) -> None:
    """Say once what produced the replay otherwise than its source, and that numbers can differ."""
    if not differences:
        return
    keys = ", ".join(sorted(differences))
    logger.warning(
        "Replay of %s: %s differ(s) from the source. The lineage holds both sides. "
        "The numbers can differ.",
        Path(source_run).name,
        keys,
    )


__all__ = [
    "api_inputs_intact",
    "check_replay_inputs",
    "locked_inputs_of",
    "producer_differences",
    "sealed_run_of",
    "warn_config_drift",
    "warn_producer_differences",
]
