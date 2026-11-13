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

A session holds one parameter set and one run per case. ``best`` is the run of
a session of one case, and ``best_by_case`` holds them all. On a session of several
cases ``best`` refuses and names ``best_by_case``: the first run would read one
basin for the whole experiment, and ``None`` would say that no run exists.
"""

from __future__ import annotations

import tomllib
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

import pandas as pd

from hydromodpy.core.exceptions import NothingThereError
from hydromodpy.core.state.result_dirs import run_dir_rel
from hydromodpy.results.errors import SeveralCasesError
from hydromodpy.results.metric_rule import PeriodWindow
from hydromodpy.results.record.manifest import is_sealed
from hydromodpy.results.session.descriptor import (
    BestCase,
    SessionDescriptor,
    SessionStatus,
    read_session,
    session_descriptor_path,
)
from hydromodpy.results.session.journal import read_trials, trial_rows
from hydromodpy.results.session.phase import PhaseDescriptor, list_phases
from hydromodpy.results.storage.contract import SESSION_CONFIG_FILENAME

if TYPE_CHECKING:
    from matplotlib.figure import Figure
    from pydantic import BaseModel

    from hydromodpy.results.run.view import Renderer, Run

TRIAL_COLUMNS: tuple[str, ...] = (
    "session_id",
    "phase",
    "restart",
    "trial",
    "case_id",
    "site",
    "cost",
    "case_cost",
    "components",
    "parameters",
    "status",
    "case_status",
    "from_cache",
    "params_hash",
    "sim_id",
    "rel_dir",
    "duration_s",
    "batch",
    "rule",
    "window",
    "solve_s",
    "reused",
)
"""Columns of the trial frame, one row per trial and per case.

``batch`` is the optimizer call that proposed the trial, ``rule`` and ``window``
say how and on which period the case was scored, ``solve_s`` is the solve time
of the trial and ``reused`` is ``rerun`` or ``no``. The five are null where
the journal does not say.
"""

PROFILE_COLUMNS: tuple[str, ...] = ("kind", "name", "reused", "lines", "duration_s", "max_rss_mb")
"""Columns of :meth:`Session.profile`, one row per kind, name and ``reused``."""

SESSION_SHOWS: Final[tuple[str, ...]] = ("table", "profile", "figure", "report")
"""The values of ``what`` that :meth:`Session.show` reads."""


class Session:
    """One calibration session, read from its directory.

    Parameters
    ----------
    session_dir
        The session directory, ``sessions/<case>[.vN]``.
    read_config
        The function that validates a sealed configuration snapshot, passed
        to the runs the session opens. Without one, ``run.hydromodpy_config``
        is refused. A session opened by ``hmp.open`` or by a ``Project``
        carries it.
    render
        The function that draws a figure or writes the report of the session.
        Without one, ``figure`` is refused.

    Raises
    ------
    FileNotFoundError
        If the directory holds no ``session.json``.

    Examples
    --------
    >>> import hydromodpy as hmp
    >>> proj = hmp.open("~/ws/projects/bretagne")  # doctest: +SKIP
    >>> session = proj.sessions["J0014010-calage"]  # doctest: +SKIP
    >>> session.trials.sort_values("cost").head()  # doctest: +SKIP
    >>> session.best.label()  # doctest: +SKIP
    """

    def __init__(
        self,
        session_dir: str | Path,
        *,
        read_config: Callable[[Mapping[str, Any]], BaseModel] | None = None,
        render: Renderer | None = None,
    ) -> None:
        directory = Path(session_dir).expanduser().resolve()
        if not session_descriptor_path(directory).is_file():
            raise FileNotFoundError(
                f"{directory} holds no {session_descriptor_path(directory).name}: "
                "it is not a calibration session"
            )
        self._dir = directory
        self._read_config = read_config
        self._render = render
        self._descriptor: SessionDescriptor | None = None

    @classmethod
    def of_run(cls, run: Any) -> Session | None:
        """Return the session that promoted ``run``, or None when no session did.

        The session is found from the lineage of the run (its ``session_id``)
        among the ``sessions/*/`` of its project, and a kept trial under
        ``sessions/<case>/trials/<n>`` is in its own session. A session figure
        asked for on a run draws this session. The session opened here keeps
        the ``read_config`` of the run, so its best run validates its
        configuration as the run does.
        """
        # Imported here: calibration_trials reads this module at import time.
        from hydromodpy.results.calibration_trials import session_dir_of

        directory = session_dir_of(run)
        if directory is None or not session_descriptor_path(directory).is_file():
            return None
        return cls(
            directory,
            read_config=getattr(run, "_read_config", None),
            render=getattr(run, "_render", None),
        )

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
    def cases(self) -> tuple[str, ...]:
        """The ids of the calibrated cases."""
        return tuple(self.descriptor.cases)

    @property
    def sites(self) -> tuple[str, ...]:
        """The sites of the calibrated cases."""
        return tuple(self.descriptor.sites)

    @property
    def windows(self) -> dict[str, PeriodWindow]:
        """The periods of the search whose best the session holds, by name."""
        return dict(self.descriptor.windows)

    @property
    def trials(self) -> pd.DataFrame:
        """Every trial of the session, one row per trial and case (:data:`TRIAL_COLUMNS`)."""
        descriptor = self.descriptor
        rows = []
        for line in read_trials(self._dir):
            for row in trial_rows(line):
                case = descriptor.cases.get(row["case_id"])
                rows.append(
                    {
                        **row,
                        "session_id": descriptor.session_id,
                        "site": None if case is None else case.site,
                    }
                )
        return pd.DataFrame(rows, columns=list(TRIAL_COLUMNS))

    def profile(self) -> pd.DataFrame:
        """Where the time of the search went, by step and by ``reused`` (:data:`PROFILE_COLUMNS`).

        It adds the profile lines of every trial the journal holds, read from the
        last line of each trial. ``lines`` counts the lines added, ``duration_s``
        sums their time and ``max_rss_mb`` is the peak of their memory. A trial read
        from the cost cache or written by a pre-release has no profile and adds nothing.
        """
        totals: dict[tuple[str, str, str], list[float]] = {}
        for line in read_trials(self._dir):
            for entry in line.profile:
                total = totals.setdefault((entry.kind, entry.name, entry.reused), [0, 0.0, 0.0])
                total[0] += 1
                total[1] += entry.duration_s or 0.0
                total[2] = max(total[2], entry.max_rss_mb or 0.0)
        rows = [
            {
                "kind": kind,
                "name": name,
                "reused": reused,
                "lines": int(lines),
                "duration_s": duration,
                "max_rss_mb": rss or None,
            }
            for (kind, name, reused), (lines, duration, rss) in sorted(totals.items())
        ]
        return pd.DataFrame(rows, columns=list(PROFILE_COLUMNS))

    @property
    def phases(self) -> list[PhaseDescriptor]:
        """The phases of a staged search, by rank; empty for a single search."""
        return list_phases(self._dir)

    def table(self, name: str) -> pd.DataFrame:
        """Return the table *name* of this session: ``trials`` or ``profile``.

        ``trials`` is :attr:`trials` and ``profile`` is :meth:`profile`. Any other
        name is refused with those two.
        """
        if name == "trials":
            return self.trials
        if name == "profile":
            return self.profile()
        raise NothingThereError(f"A session holds the tables trials and profile, not {name!r}.")

    def figure(
        self,
        name: str | None = None,
        *,
        request: Mapping[str, Any] | None = None,
        draw: Callable[..., Any] | None = None,
        save: str | Path | None = None,
        dpi: int | None = None,
        theme: str | None = None,
        engine: str | None = None,
        time: str | None = None,
        data: bool = False,
        **options: Any,
    ) -> Figure | Path | dict[str, Any]:
        """Draw the registered ``session`` figure *name* of this session.

        The arguments are those of :meth:`hydromodpy.results.run.view.Run.figure`.
        A figure of another subject refuses the session.

        Raises
        ------
        hydromodpy.core.exceptions.CommandUsageError
            If the session was not opened by ``hydromodpy.open`` or a project.
        """
        from hydromodpy.results.run.view import figure_of

        return figure_of(
            self,
            name,
            request,
            {
                **options,
                "draw": draw,
                "save": save,
                "dpi": dpi,
                "theme": theme,
                "engine": engine,
                "time": time,
            },
            data=data,
        )

    def show(self, what: str, **options: Any) -> Any:
        """Read one thing of this session: ``table``, ``profile``, ``figure`` or ``report``."""
        from hydromodpy.results.run.view import show_of

        return show_of(self, what, options, SESSION_SHOWS)

    @property
    def best_cost(self) -> float | None:
        """The cost of the best trial, ``None`` without one."""
        best = self.descriptor.best
        return None if best is None else best.cost

    @property
    def best_parameters(self) -> dict[str, float]:
        """The one parameter set of the best trial, empty without one."""
        best = self.descriptor.best
        return {} if best is None else dict(best.parameters)

    @property
    def best_by_case(self) -> dict[str, Run | None]:
        """The run of the best trial in each case, ``None`` where it is missing.

        Empty while no trial is held as best.
        """
        best = self.descriptor.best
        if best is None:
            return {}
        return {
            case_id: self._run_of(case_id, case, best.trial) for case_id, case in best.cases.items()
        }

    @property
    def best(self) -> Run | None:
        """The run the best trial was promoted to, read from its directory.

        The descriptor names the run of the best trial; without that hint, the
        run paired with the session (``runs/<session name>``) is taken when it
        carries the same id. ``None`` while no run holds the best trial, or
        when the search keeps no single best.

        Raises
        ------
        SeveralCasesError
            If the session calibrates several cases: read ``best_by_case``.
        """
        case_id = self.descriptor.only_case
        if case_id is None:
            raise SeveralCasesError(
                f"session {self.name} holds one run per case ({', '.join(self.cases)}): "
                "read best_by_case."
            )
        return self.best_by_case.get(case_id)

    def _run_of(self, case_id: str, case: BestCase, trial: int) -> Run | None:
        """Return the run the best trial became in one case, or ``None``.

        Without a ``sim_id`` the paired run is taken only when its seal names this
        session and this trial: it may hold an older best of the same session.
        """
        from hydromodpy.results.run.view import open_run_dir

        project_root = self._dir.parent.parent
        hints = [case.rel_dir] if case.rel_dir else []
        if self.descriptor.only_case == case_id:
            hints.append(run_dir_rel(self.name))
        for rel_dir in hints:
            directory = project_root / rel_dir
            if not is_sealed(directory):
                continue
            run = open_run_dir(directory, read_config=self._read_config, render=self._render)
            if case.sim_id is not None:
                if run.sim_id == case.sim_id:
                    return run
                continue
            by = run.checks.calibrated_by
            if by is not None and by.session_id == self.descriptor.session_id and by.trial == trial:
                return run
        return None

    def __repr__(self) -> str:
        return f"Session(name={self.name!r}, status={self.status!r})"


__all__ = ["PROFILE_COLUMNS", "TRIAL_COLUMNS", "Session"]
