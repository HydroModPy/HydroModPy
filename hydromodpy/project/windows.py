"""Cut a long transient run into windows and play them one after the other.

``[simulation.time] window_length`` cuts the stress periods into windows that end
on a period end. Each window is a run of its own, named ``<name>_w<k>``, sealed
with its ``final_state/``. Window ``k > 1`` starts from the final state of window
``k - 1``, which enters the run as the input ``initial_state`` and, by its digest,
the request id. A window already sealed with the same request is skipped, so a
chain stopped in window 3 resumes by playing it again.

A resume names the chain, ``island``, or the window that stopped, ``island_w3``.
Without a file it reads the configuration that window froze, and the chain goes on
from that window to the last.

``cut_grid`` is what the project reads to put one window on the setup context.
``run_windows`` is the driver, and ``play`` is the function that plays one window.
``recorded_window_source`` is the source a sealed window replays from.
"""

from __future__ import annotations

import copy
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

from hydromodpy.core.exceptions import ConfigError, ResumeError
from hydromodpy.core.logging import get_logger
from hydromodpy.core.state.layout import runs_dir_for
from hydromodpy.core.time.window import (
    ChainWindow,
    chain_windows,
    window_grid,
)
from hydromodpy.results.catalog.registration import split_stem_version
from hydromodpy.results.manifest import is_sealed
from hydromodpy.results.outcome import read_outcome
from hydromodpy.results.record import read_inputs
from hydromodpy.results.storage.attempt import run_dir_for_name
from hydromodpy.results.storage.contract import RUN_CONFIG_FILENAME
from hydromodpy.workflow.steps.prepare_solver.restart import (
    INITIAL_STATE_VARIABLE,
    WindowSource,
)

if TYPE_CHECKING:
    from hydromodpy.project.environment import Environment
    from hydromodpy.project.request import RunOutcome, RunRequest

logger = get_logger(__name__)

Play = Callable[..., "RunOutcome | None"]
"""Plays one window: ``play(request, window_source=...)``, the worker of one run."""


def window_run_name(stem: str, index: int, count: int) -> str:
    """The name of window ``index`` of ``count``, with ``index`` padded to the width of ``count``.

    ``island_w1`` for a chain of fewer than ten windows, ``island_w01`` from ten,
    so ``ls`` sorts the runs in the order of the chain.
    """
    return f"{stem}_w{index:0{len(str(count))}d}"


def cut_grid(grid: Any, time_config: Any) -> tuple[Any, ChainWindow | None]:
    """Return the grid a run solves and the window it is, from the whole grid of the simulation.

    Without ``window_length``, or with ``window = "all"``, the run is the whole
    simulation and the grid comes back as it is. With a window number the grid of
    that window comes back with the window itself. A window that does not exist
    is refused with the number of windows the length makes.
    """
    length = getattr(time_config, "window_length", None)
    chosen = getattr(time_config, "window", "all")
    if length is None or chosen == "all":
        return grid, None
    windows = chain_windows(grid, length)
    if not 1 <= int(chosen) <= len(windows):
        raise ConfigError(
            f"simulation.time.window = {chosen} picks a window that does not exist: "
            f"window_length = {length!r} cuts this run into {len(windows)} window(s)."
        )
    window = windows[int(chosen) - 1]
    return window_grid(grid, window), window


def named_window(ref: str | None, count: int, project_root: Path) -> tuple[str, int] | None:
    """The chain and the window a resume names, when ``ref`` is the run of a window.

    ``island_w3`` names window 3 of the chain ``island`` when it is the name
    :func:`window_run_name` gives that window and a run of that name exists. A
    chain whose own name ends in ``_w<k>`` is still named by its name, because no
    run carries the bare name of a chain.
    """
    if not ref:
        return None
    stem, _, digits = ref.rpartition("_w")
    if not stem or not digits.isdigit() or not 1 <= int(digits) <= count:
        return None
    if window_run_name(stem, int(digits), count) != ref:
        return None
    if run_dir_for_name(Path(project_root), ref) is None:
        return None
    return stem, int(digits)


def chain_length(cfg: Any) -> int | None:
    """The number of windows of the document, or ``None`` when it asks for no chain."""
    time_config = getattr(getattr(cfg, "simulation", None), "time", None)
    if getattr(time_config, "window_length", None) is None:
        return None
    from hydromodpy.core.time import require_flow_simulation_time_grid

    return len(chain_windows(require_flow_simulation_time_grid(cfg), time_config.window_length))


def window_document(document: Mapping[str, Any], index: int) -> dict[str, Any]:
    """A copy of ``document`` that plays window ``index`` alone."""
    copied = copy.deepcopy(dict(document))
    simulation = copied.setdefault("simulation", {})
    simulation.setdefault("time", {})["window"] = int(index)
    return copied


def newest_sealed_run(project_root: Path, name: str) -> Path | None:
    """The newest sealed version of the run ``name`` (``name``, ``name.v2``, ...), or ``None``."""
    runs = runs_dir_for(Path(project_root))
    if not runs.is_dir():
        return None
    found: list[tuple[int, Path]] = []
    for entry in runs.iterdir():
        stem, version = split_stem_version(entry.name)
        if entry.is_dir() and stem == name and is_sealed(entry):
            found.append((1 if version is None else version, entry))
    return max(found)[1] if found else None


def recorded_window_source(run_dir: Path, project_root: Path) -> WindowSource | None:
    """The source a sealed window started from, read from its ``initial_state`` input.

    A replay of window ``k > 1`` starts where the window started. ``None`` for a
    run that started on its own, window 1 included. A source that is no longer a
    sealed run of the project is refused before anything runs.
    """
    row = next(
        (
            entry
            for entry in read_inputs(run_dir).inputs
            if entry.variable == INITIAL_STATE_VARIABLE
        ),
        None,
    )
    if row is None:
        return None
    folder = Path(row.path)
    source_dir = (folder if folder.is_absolute() else Path(project_root) / folder).parent
    if not is_sealed(source_dir):
        raise ConfigError(
            f"{Path(run_dir).name} started from {row.path}, and no sealed run is there in "
            f"{project_root}. Replay the window in the project that holds the window before it."
        )
    return source_of(source_dir)


def source_of(run_dir: Path) -> WindowSource:
    """The :class:`WindowSource` a sealed window run is."""
    from hydromodpy.results.manifest import read_manifest

    manifest = read_manifest(run_dir)
    sim_id = manifest.get("run", {}).get("sim_id")
    return WindowSource(run_dir=Path(run_dir), sim_id=None if sim_id is None else str(sim_id))


def window_source_for(
    request: RunRequest,
    cfg: Any,
    *,
    base: Path,
    environment: Environment,
    index: int,
    count: int,
    stem: str,
) -> WindowSource:
    """Find and check the source of window ``index`` played alone, before anything is claimed.

    The source is the newest sealed version of window ``index - 1``. It is refused
    when it does not exist, and when it was played with another request than this
    document asks at that window: its recorded request id is compared with the
    one computed for the same document at window ``index - 1`` and the state that
    window started from.
    """
    project_root = Path(cfg.workspace.project_root)
    previous = window_run_name(stem, index - 1, count)
    run_dir = newest_sealed_run(project_root, previous)
    if run_dir is None:
        raise ConfigError(
            f"window {index} starts from the final state of window {index - 1}; run window "
            f'{index - 1} first, or set window = "all". No sealed run named {previous!r} is in '
            f"{runs_dir_for(project_root)}."
        )
    recorded = read_outcome(run_dir)
    if recorded is None or recorded.request_id != _expected_request_id(
        request, cfg, run_dir, base=base, environment=environment, index=index - 1
    ):
        raise ConfigError(
            f"{run_dir.name} was played with another configuration than this document asks "
            f"for window {index - 1}, so window {index} cannot start from it. Run the window "
            f'again with this document, or set window = "all".'
        )
    return source_of(run_dir)


def _expected_request_id(
    request: RunRequest,
    cfg: Any,
    run_dir: Path,
    *,
    base: Path,
    environment: Environment,
    index: int,
) -> str:
    """The request id this document gives window ``index``, started from the state ``run_dir`` recorded.

    The ``set`` of the request applies, as it does to the window when it runs.
    """
    from hydromodpy.config.loading import load
    from hydromodpy.data.loading.inputs import resolve_inputs
    from hydromodpy.project.dispatch.workflow import _changed
    from hydromodpy.workflow.solution_key import request_id_of
    from hydromodpy.workflow.steps.prepare_solver.restart import source_state_digests

    document = window_document(request.config, index)
    cfg_at = _changed(load(document, base, source_path=_source_file(request, base)), request.set)
    resolved = resolve_inputs(
        cfg_at, bounds=environment.bounds, data_dir=Path(cfg_at.workspace.data_path)
    )
    window_state = next(
        (
            entry.sha256
            for entry in read_inputs(run_dir).inputs
            if entry.variable == INITIAL_STATE_VARIABLE
        ),
        None,
    )
    return request_id_of(
        cfg_at,
        resolved,
        search=False,
        window_state=window_state,
        source_states=source_state_digests(cfg_at, Path(cfg.workspace.project_root)),
    )


def _source_file(request: RunRequest, base: Path) -> Path | None:
    """The file the request was read from, absolute, or ``None``."""
    if request.source is None:
        return None
    named = Path(request.source)
    return named if named.is_absolute() else Path(base) / named


def _frozen_config_of(request: RunRequest, base: Path, run_dir: Path | None) -> bool:
    """Whether the request was read from the ``config.toml`` that ``run_dir`` froze."""
    source = _source_file(request, base)
    if source is None or run_dir is None:
        return False
    return source.resolve() == (Path(run_dir) / RUN_CONFIG_FILENAME).resolve()


def _interrupted_windows(
    project_root: Path, stem: str, indices: list[int], count: int
) -> frozenset[str]:
    """The windows whose newest run holds an attempt that stopped before its seal."""
    found: set[str] = set()
    for index in indices:
        name = window_run_name(stem, index, count)
        run_dir = run_dir_for_name(project_root, name)
        if run_dir is not None and not is_sealed(run_dir):
            found.add(name)
    return frozenset(found)


def run_windows(
    request: RunRequest,
    *,
    cfg: Any,
    base: Path,
    environment: Environment,
    play: Play,
) -> RunOutcome | None:
    """Play the windows the document asks for, in order, and return the outcome of the last.

    ``cfg`` is the loaded document with the ``set`` of the request applied, so the
    windows are counted on the grid the runs solve. ``play(window_request, window_source=...)``
    plays one window as a run of its own: the same document with
    ``simulation.time.window`` set to the window, named by :func:`window_run_name`.
    With ``window = "all"`` each window starts from the one played just before,
    and a window already sealed with the same request is given back by ``play``.
    A stop in one window raises and ends the chain. A window number plays that
    window alone, from the newest sealed version of the window before it.

    A resume that names the chain continues each window that stopped. A resume
    that names window ``k`` continues that window, from the newest sealed version
    of the window before it, then plays the windows after it when the document
    plays them all. The ``config.toml`` window ``k`` froze plays them all, so
    ``hmp run --resume island_w3`` without a file goes on to the last window.

    ``set`` may not change the window keys: the document is what cuts the run.
    """
    touched = sorted(key for key in request.set if "simulation.time.window" in key)
    if touched:
        raise ConfigError(
            f"--set cannot change {', '.join(touched)}: write the window keys in the document."
        )
    time_config = cfg.simulation.time
    count = chain_length(cfg)
    project_root = Path(cfg.workspace.project_root)
    chosen = time_config.window
    named = named_window(request.resume, count, project_root)
    if named is None:
        stem = request.resume or request.name or cfg.simulation.name
        first = 1
    else:
        stem, first = named
        if _frozen_config_of(request, base, run_dir_for_name(project_root, request.resume)):
            chosen = "all"
        elif chosen != "all" and int(chosen) != first:
            raise ResumeError(
                f"resume {request.resume!r} names window {first}, and the document plays "
                f"window {chosen}. Resume the window the document plays, or set "
                'window = "all".'
            )
    if not stem:
        raise ConfigError(
            "A run cut into windows is named after its run name, and this request names none. "
            "Name the run with --case or [simulation] name."
        )
    indices = list(range(first, count + 1)) if chosen == "all" else [int(chosen)]
    if indices[-1] > count:
        raise ConfigError(
            f"simulation.time.window = {chosen} picks a window that does not exist: "
            f"window_length = {time_config.window_length!r} cuts this run into {count} window(s)."
        )
    interrupted = _interrupted_windows(project_root, stem, indices, count)
    if request.resume is not None and not interrupted:
        raise ResumeError(
            f"resume {request.resume!r}: no window of this run holds an interrupted attempt "
            "to continue."
        )
    if named is not None and request.resume not in interrupted:
        raise ResumeError(
            f"resume {request.resume!r}: that window holds no interrupted attempt to continue."
        )
    outcome: RunOutcome | None = None
    for index in indices:
        name = window_run_name(stem, index, count)
        if index == 1:
            source = None
        elif outcome is not None and outcome.run_dir is not None:
            source = source_of(Path(outcome.run_dir))
        else:
            source = window_source_for(
                request,
                cfg,
                base=base,
                environment=environment,
                index=index,
                count=count,
                stem=stem,
            )
        logger.info("window %d of %d: run %s", index, count, name)
        window_request = request.model_copy(
            update={
                "config": window_document(request.config, index),
                "name": name,
                "resume": name if request.resume is not None and name in interrupted else None,
            }
        )
        outcome = play(window_request, window_source=source)
        if outcome is None:
            return None
        if outcome.identical_to is not None and index < indices[-1]:
            from hydromodpy.project.dispatch.workflow import identical_run_message

            logger.info("%s", identical_run_message(outcome.identical_to, str(outcome.sim_id)))
    return outcome


__all__ = [
    "cut_grid",
    "named_window",
    "newest_sealed_run",
    "recorded_window_source",
    "run_windows",
    "source_of",
    "window_document",
    "window_run_name",
    "window_source_for",
]
