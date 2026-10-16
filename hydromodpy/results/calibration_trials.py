"""Read the trials and the phases of the session a run was promoted from.

A figure about a calibration wants the calibration, not one trial: the run
promoted from a session carries ``lineage.session_id`` in its seal, and the
session journals every trial under ``sessions/<case>/trials.jsonl``. The two
readers here resolve a run, or a run-shaped adapter that carries its rows
itself, into the same frames, so a figure has one call to make and no shape
to test for. Nothing is read from the index.
"""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pandas as pd

from hydromodpy.core.state.paths import parse_rel_dir
from hydromodpy.results.run.sealed import lineage_of
from hydromodpy.results.run.view import Run
from hydromodpy.results.session.descriptor import find_session_dir, read_session
from hydromodpy.results.session.journal import read_trials, trial_row
from hydromodpy.results.session.phase import list_phases
from hydromodpy.results.storage.contract import SESSION_CONFIG_FILENAME

__all__ = ("calibration_sessions", "calibration_trials", "session_dir_of")

TRIAL_COLUMNS: tuple[str, ...] = (
    "session_id",
    "phase",
    "restart",
    "iteration",
    "sim_id",
    "rel_dir",
    "params_hash",
    "parameters",
    "objective_value",
    "metrics",
    "status",
    "from_cache",
    "duration_s",
)
"""Columns of the trial frame; ``iteration`` is the trial number, unique in the session."""


def _rows_carried_by(source: Any) -> pd.DataFrame | None:
    """Return the rows a run-shaped adapter carries itself, if it carries any."""
    rows = getattr(source, "calibration_iterations", None)
    if rows is None:
        return None
    return rows.copy() if isinstance(rows, pd.DataFrame) else pd.DataFrame(list(rows))


def _run_dir_of(source: Any) -> Path | None:
    """Return the directory of a run, the ``dir`` of the source, or None without one."""
    directory = getattr(source, "dir", None)
    return Path(directory) if directory is not None else None


def _split_project_root(run_dir: Path) -> tuple[Path, str] | None:
    """Return the project root a run directory sits in and its relative form, or None.

    The two forms a run directory takes are those ``parse_rel_dir`` knows:
    the trailing parts of the path are tried against them, the shorter first.
    """
    parts = run_dir.resolve().parts
    for depth in (2, 4):
        if len(parts) < depth:
            continue
        rel = "/".join(parts[-depth:])
        try:
            parse_rel_dir(rel)
        except ValueError:
            continue
        return Path(*parts[:-depth]), rel
    return None


def session_dir_of(source: Any, *, session_id: str | None = None) -> Path | None:
    """Return the session directory a run was promoted from, or None.

    The run names its session by id in its lineage
    (:func:`~hydromodpy.results.run.sealed.lineage_of`, or the ``lineage`` of a
    run-shaped source); the project root is read off the run directory, and
    the session that carries that id is found among ``sessions/*/session.json``. A kept trial under
    ``sessions/<case>/trials/<n>`` is in its own session.
    """
    run_dir = _run_dir_of(source)
    if run_dir is None:
        return None
    split = _split_project_root(run_dir)
    if split is None:
        return None
    project_root, rel = split
    parsed = parse_rel_dir(rel)
    if session_id is None and parsed.kind == "trial":
        return project_root / parsed.as_posix().rsplit("/", 2)[0]
    wanted = session_id
    if wanted is None:
        lineage = (
            lineage_of(source) if isinstance(source, Run) else getattr(source, "lineage", None)
        )
        wanted = getattr(lineage, "session_id", None)
    if wanted is None:
        return None
    return find_session_dir(project_root, str(wanted))


def _trial_frame(session_dir: Path) -> pd.DataFrame:
    """Return the trials of one session as the frame the figures read."""
    descriptor = read_session(session_dir)
    rows = [
        {"session_id": descriptor.session_id, **trial_row(line)}
        for line in read_trials(session_dir)
    ]
    return pd.DataFrame(rows, columns=list(TRIAL_COLUMNS))


def calibration_trials(
    source: Any, *, session_id: str | None = None, phase: str | None = None
) -> pd.DataFrame:
    """Return the trials of the session ``source`` was promoted from.

    Parameters
    ----------
    source
        A run (``dir`` and ``lineage``), or the run-shaped adapter the
        calibration report builds, which carries its rows itself.
    session_id
        Read that session instead of the one the run names.
    phase
        Keep only the trials of that phase.

    Raises
    ------
    ValueError
        When no trial can be read. The message says which of the two cases it
        is, because "no session" and "the session recorded nothing" call
        for different answers from the reader.
    """
    frame = _rows_carried_by(source)
    if frame is None:
        session_dir = session_dir_of(source, session_id=session_id)
        if session_dir is None:
            raise ValueError(
                f"no calibration trial can be read from {type(source).__name__}: it names no "
                "session and carries no calibration_iterations."
            )
        frame = _trial_frame(session_dir)
    elif session_id is not None and "session_id" in frame.columns:
        wanted = str(session_id).replace("-", "").lower()
        frame = frame[frame["session_id"].map(lambda v: str(v).replace("-", "").lower()) == wanted]
    if phase is not None and "phase" in frame.columns:
        frame = frame[frame["phase"] == phase]
    if frame.empty:
        scope = "" if session_id is None else f" for session {session_id!r}"
        raise ValueError(f"no trial recorded{scope} by this calibration.")
    return frame.reset_index(drop=True)


def _session_config(session_dir: Path) -> dict[str, Any]:
    """Return the ``[calibration]`` table of the frozen configuration of a session."""
    target = session_dir / SESSION_CONFIG_FILENAME
    if not target.is_file():
        return {}
    with target.open("rb") as handle:
        document = tomllib.load(handle)
    calibration = document.get("calibration")
    return dict(calibration) if isinstance(calibration, Mapping) else {}


def _session_frame(session_dir: Path) -> pd.DataFrame:
    """Return one row per phase of a session, or one row when it ran no phase."""
    descriptor = read_session(session_dir)
    config = _session_config(session_dir)
    base = {
        "session_id": descriptor.session_id,
        "case_id": descriptor.case_id,
        "site": descriptor.site,
        "method": descriptor.method,
        "objective_name": descriptor.objective_name,
        "status": descriptor.status,
        "started_at": descriptor.started_at,
        "ended_at": descriptor.ended_at,
        "best_trial": descriptor.best.trial if descriptor.best is not None else None,
        "best_sim_id": descriptor.best.sim_id if descriptor.best is not None else None,
        "root_search": descriptor.root_search,
        "search_space": descriptor.search_space,
        "config": config,
    }
    phases = list_phases(session_dir)
    if not phases:
        return pd.DataFrame([{**base, "phase_name": None, "phase_index": None, "frozen": {}}])
    return pd.DataFrame(
        [
            {
                **base,
                "status": phase.status,
                "phase_name": phase.name,
                "phase_index": phase.index,
                "frozen": dict(phase.frozen),
                "best_trial": phase.best.trial if phase.best is not None else None,
                "best_sim_id": phase.best.sim_id if phase.best is not None else None,
            }
            for phase in phases
        ]
    )


def calibration_sessions(source: Any) -> pd.DataFrame:
    """Return the session rows reachable from ``source``, one per phase.

    A run-shaped adapter carries its own rows. A run reads the session its
    seal names. A source with no session behind it is not an error: the
    frame is empty, because a figure drawn without the session rows still
    draws, one phase to the chain.
    """
    frame = getattr(source, "calibration_sessions", None)
    if frame is not None:
        return frame.copy() if isinstance(frame, pd.DataFrame) else pd.DataFrame(list(frame))
    session_dir = session_dir_of(source)
    if session_dir is None:
        return pd.DataFrame()
    return _session_frame(session_dir)
