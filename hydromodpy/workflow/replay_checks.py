"""What a replay of a sealed run checks: its inputs, its configuration, its solver.

``hmp run <run>/config.toml --frozen`` replays a run from its own record: the
digests of ``inputs.json`` and ``manifest.json`` beside the file, and
``config.resolved.toml``. A project lockfile plays no part there: it pins a project
TOML. ``hmp catalog rerun`` and ``Project.rerun`` warn where ``--frozen`` refuses,
and record what moved in the lineage of the new run.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from hydromodpy.core.exceptions import FrozenDataError
from hydromodpy.core.logging import get_logger
from hydromodpy.core.state.portable import decode_workspace_path
from hydromodpy.core.toml_io.paths import source_of_effective_copy
from hydromodpy.core.workspace.resolve import locate_workspace_root
from hydromodpy.results.manifest import read_manifest
from hydromodpy.results.record import read_inputs, read_provenance
from hydromodpy.results.storage.contract import (
    RUN_CONFIG_FILENAME,
    RUN_INPUTS_FILENAME,
    RUN_MANIFEST_FILENAME,
    RUN_RESOLVED_CONFIG_FILENAME,
)
from hydromodpy.results.storage.digests import sha256_streaming
from hydromodpy.workflow.steps.prepare_solver.resolved import build_drift, config_drift

logger = get_logger(__name__)


def check_replay(
    config: Any, run_dir: Path, *, project_root: Path, inputs_checked: bool = False
) -> None:
    """Refuse a replay on other bytes or another configuration, warn on another binary.

    A published copy has checked its inputs against its install index already.
    """
    if not inputs_checked:
        refuse_changed_inputs(run_dir, project_root)
    warning = solver_binary_warning(run_dir)
    if warning is not None:
        logger.warning("--frozen: %s", warning)
    _refuse_config_drift(config, run_dir, project_root=project_root)


def warn_replay_differences(source_run: Path, replay_run: Path) -> None:
    """Warn about what a finished replay did otherwise than its source."""
    for line in replay_differences(source_run, replay_run):
        logger.warning("--frozen: %s: %s", Path(source_run).name, line)


def sealed_run_of(config_path: Path) -> Path | None:
    """Return the sealed run *config_path* is the frozen configuration of, or None.

    The effective copy that ``--set`` writes beside the file stands for that file.
    """
    path = source_of_effective_copy(Path(config_path).resolve())
    folder = path.parent
    if path.name != RUN_CONFIG_FILENAME:
        return None
    if (folder / RUN_MANIFEST_FILENAME).is_file() and (folder / RUN_INPUTS_FILENAME).is_file():
        return folder
    return None


def _loaded_inputs(run_dir: Path) -> dict[str, tuple[str, str]]:
    """Return ``{path: (name, sha256)}`` of the files ``inputs.json`` says the run read."""
    return {
        str(entry.path): (str(entry.variable), str(entry.sha256))
        for entry in read_inputs(run_dir).inputs
        if entry.path and entry.sha256
    }


def _recorded_inputs(run_dir: Path) -> dict[str, tuple[str, str]]:
    """Return what the record of a run says it read: ``inputs.json``, then its manifest.

    The manifest lists what the configuration declares, a folder among them. A path
    is relative to the workspace.
    """
    recorded = _loaded_inputs(run_dir)
    for entry in read_manifest(run_dir).get("inputs") or ():
        path, digest = entry.get("path"), entry.get("sha256")
        if path and digest and str(path) not in recorded:
            recorded[str(path)] = (str(entry.get("role") or "input"), str(digest))
    return recorded


def _input_mismatches(run_dir: Path, project_root: Path) -> list[str]:
    """Return one line per recorded input that is missing or has another digest here.

    A declared folder only has to be there: the run read some files of it, which the
    record lists one by one, and a file added beside them is no other input.
    """
    root = Path(project_root).resolve()
    workspace = locate_workspace_root(root) or root
    lines: list[str] = []
    for path, (name, sealed) in sorted(_recorded_inputs(run_dir).items()):
        located = decode_workspace_path(workspace, path)
        if not located.exists():
            lines.append(f"{name} ({path}): sealed {sealed}, missing from {located}")
            continue
        if located.is_dir():
            continue
        found = sha256_streaming(located)
        if found != sealed:
            lines.append(f"{name} ({path}): sealed {sealed}, found {found}")
    return lines


def refuse_changed_inputs(run_dir: Path, project_root: Path) -> None:
    """Refuse a ``--frozen`` replay whose inputs are not the bytes the run read."""
    lines = _input_mismatches(run_dir, project_root)
    if lines:
        raise FrozenDataError(
            f"--frozen: {len(lines)} input(s) of {run_dir.name} differ from its record. "
            "Restore them, or replay without --frozen:\n  " + "\n  ".join(lines)
        )


def _refuse_config_drift(config: Any, run_dir: Path, *, project_root: Path) -> None:
    """Refuse a ``--frozen`` replay whose effective configuration differs from the sealed one."""
    drift = config_drift(config, run_dir, project_root=project_root)
    if drift is None:
        raise FrozenDataError(
            f"--frozen: {run_dir.name} holds no {RUN_RESOLVED_CONFIG_FILENAME}, so its "
            "configuration cannot be compared. Replay it without --frozen."
        )
    if drift:
        raise FrozenDataError(
            f"--frozen: the configuration read from {run_dir.name} differs from the one it "
            f"sealed in {RUN_RESOLVED_CONFIG_FILENAME}, on {len(drift)} key(s). A default moved, "
            "or the file changed. Install the version the run names, write the sealed value "
            "in the file, or replay without --frozen:\n  "
            + "\n  ".join(item.line() for item in drift)
        )


def warn_config_drift(
    config: Any, run_dir: Path | None, *, intended: Iterable[str] = ()
) -> dict[str, dict[str, Any]]:
    """Warn about each key a rerun takes otherwise than its source, and return them.

    The result is what ``lineage.drift`` records. *intended* names what the caller
    asked to change.
    """
    if run_dir is None:
        return {}
    project_root = Path(config.workspace.project_root)
    drift = config_drift(config, run_dir, project_root=project_root, intended=intended)
    if drift is None:
        logger.warning(
            "%s holds no %s: this rerun cannot say whether a default moved since.",
            Path(run_dir).name,
            RUN_RESOLVED_CONFIG_FILENAME,
        )
        return {}
    for item in drift:
        logger.warning("Rerun of %s takes another value. %s", Path(run_dir).name, item.line())
    return {item.key: item.record() for item in drift}


def solver_binary_warning(run_dir: Path) -> str | None:
    """Return the warning when the solver binary here is not the one the run recorded."""
    from hydromodpy.results.run.environment import solver_binary_identity
    from hydromodpy.solver.modflow_common.binaries import resolve_solver_engine

    solver: Mapping[str, Any] = read_provenance(run_dir).solver
    name, sealed = solver.get("name"), solver.get("binary_sha256")
    if not name or not sealed:
        return None
    mode = str(solver.get("execution_mode") or "subprocess")
    engine = resolve_solver_engine(str(name), execution_mode=mode)
    if engine is None:
        return None
    found, version = solver_binary_identity(engine.path)
    if found == sealed:
        return None
    return (
        f"{name}: the run recorded {solver.get('version') or 'an unknown version'} "
        f"(sha256 {sealed}), this machine runs {version or engine.version or 'an unknown version'} "
        f"(sha256 {found}). The numbers can differ."
    )


def replay_differences(source_run: Path, replay_run: Path) -> list[str]:
    """Return what a finished replay did otherwise than its source: its build, its inputs.

    A file is told by its digest: a replay may read the same bytes elsewhere.
    """
    lines = [
        f"the build decided otherwise. {item.line()}"
        for item in build_drift(source_run, replay_run)
    ]
    read_by_source = {digest for _name, digest in _loaded_inputs(source_run).values()}
    for path, (name, digest) in sorted(_loaded_inputs(replay_run).items()):
        if digest not in read_by_source:
            lines.append(f"{name} ({path}): read here with sha256 {digest}, the source run did not")
    return lines


__all__ = [
    "check_replay",
    "refuse_changed_inputs",
    "replay_differences",
    "sealed_run_of",
    "solver_binary_warning",
    "warn_config_drift",
    "warn_replay_differences",
]
