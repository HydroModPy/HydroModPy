"""Read-only view of one calibration session directory, ``sessions/<case>/``.

What
----
:class:`Session` reads what a search left on disk: its descriptor
(``session.json``), its trials (``trials.jsonl``), its phases
(``phases/<phase>/session.json``), its frozen configuration
(``config.toml``) and the run its best trial was promoted to. It reads the
directory alone, never the index, so a session copied out of its project
reads the same.

Why
---
``proj.sessions["<case>"]`` and ``hmp.open(<session dir>)`` hand back one
object with the words of the CLI: ``trials``, ``best``, ``phases``,
``config``. The figures and the report read the same trial frame
(:data:`TRIAL_COLUMNS`) through :mod:`hydromodpy.results.calibration_trials`.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pandas as pd

from hydromodpy.core.state.paths import run_dir_rel
from hydromodpy.results.manifest import is_sealed
from hydromodpy.results.session.descriptor import (
    SessionDescriptor,
    SessionStatus,
    read_session,
    session_descriptor_path,
)
from hydromodpy.results.session.journal import read_trials, trial_row
from hydromodpy.results.session.phase import PhaseDescriptor, list_phases
from hydromodpy.results.storage.contract import SESSION_CONFIG_FILENAME

if TYPE_CHECKING:
    from hydromodpy.results.run.view import Run

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


class Session:
    """One calibration session, read from its directory.

    Parameters
    ----------
    session_dir
        The session directory, ``sessions/<case>[.vN]``.

    Raises
    ------
    FileNotFoundError
        If the directory holds no ``session.json``.

    Examples
    --------
    >>> import hydromodpy as hmp
    >>> proj = hmp.open("~/ws/projects/bretagne")  # doctest: +SKIP
    >>> session = proj.sessions["J0014010-calage"]  # doctest: +SKIP
    >>> session.trials.sort_values("objective_value").head()  # doctest: +SKIP
    >>> session.best.label()  # doctest: +SKIP
    """

    def __init__(self, session_dir: str | Path) -> None:
        directory = Path(session_dir).expanduser().resolve()
        if not session_descriptor_path(directory).is_file():
            raise FileNotFoundError(
                f"{directory} holds no {session_descriptor_path(directory).name}: "
                "it is not a calibration session"
            )
        self._dir = directory
        self._descriptor: SessionDescriptor | None = None

    @property
    def dir(self) -> Path:
        """The session directory."""
        return self._dir

    @property
    def name(self) -> str:
        """Name of the session directory, ``<case>[.vN]``."""
        return self._dir.name

    @property
    def descriptor(self) -> SessionDescriptor:
        """The descriptor, ``session.json``, read once."""
        if self._descriptor is None:
            self._descriptor = read_session(self._dir)
        return self._descriptor

    @property
    def status(self) -> SessionStatus:
        """Where the search stands: running, completed, partial, aborted or failed."""
        return self.descriptor.status

    @property
    def config(self) -> dict[str, Any]:
        """The frozen configuration the session ran, ``config.toml``, as a mapping.

        Empty when the session wrote none.
        """
        target = self._dir / SESSION_CONFIG_FILENAME
        if not target.is_file():
            return {}
        with target.open("rb") as handle:
            return tomllib.load(handle)

    @property
    def trials(self) -> pd.DataFrame:
        """Every trial of the session, one row each, by trial number (:data:`TRIAL_COLUMNS`)."""
        session_id = self.descriptor.session_id
        rows = [{"session_id": session_id, **trial_row(line)} for line in read_trials(self._dir)]
        return pd.DataFrame(rows, columns=list(TRIAL_COLUMNS))

    @property
    def phases(self) -> list[PhaseDescriptor]:
        """The phases of a staged search, by rank; empty for a single search."""
        return list_phases(self._dir)

    @property
    def best(self) -> Run | None:
        """The run the best trial was promoted to, read from its directory.

        The descriptor names the run of the best trial; without that hint, the
        run paired with the session (``runs/<session name>``) is taken when it
        carries the same id. ``None`` while no run holds the best trial.
        """
        from hydromodpy.results.run.view import open_run_dir

        best = self.descriptor.best
        if best is None:
            return None
        project_root = self._dir.parent.parent
        hints = [best.rel_dir] if best.rel_dir else []
        hints.append(run_dir_rel(self.name))
        for rel_dir in hints:
            directory = project_root / rel_dir
            if not is_sealed(directory):
                continue
            run = open_run_dir(directory)
            if best.sim_id is None or run.sim_id == best.sim_id:
                return run
        return None

    def __repr__(self) -> str:
        return f"Session(name={self.name!r}, status={self.status!r})"


__all__ = ["TRIAL_COLUMNS", "Session"]
