"""Calibration session data structures and loaders.

Two concerns live here, both purely data-side:

1. :class:`CalibrationReport` - structured return type of
   ``run_calibration_cli`` and ``Project.calibrate``. Exposes session metadata
   plus a lazy accessor for the trial history.
2. :class:`SessionReportData` + :func:`load_session_report_data` - read
   one calibration session back from ``sessions/<case>/`` and return a plain
   dataclass ready to be handed to the display layer for HTML rendering. The
   rendering itself lives in :mod:`hydromodpy.reporting.calibration_report`;
   this module never imports ``hydromodpy.display`` or ``hydromodpy.reporting``.

Everything is read from the disk: the session descriptor, the trial journal,
the frozen configuration and the tables of the promoted run. The index is
never opened.
"""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from hydromodpy.core.logging import get_logger
from hydromodpy.results.session.descriptor import (
    ScoredSamples,
    read_session,
    scored_samples_text,
)
from hydromodpy.results.session.journal import read_trials
from hydromodpy.results.storage.contract import (
    PARQUET_FILE_SUFFIX,
    SESSION_CONFIG_FILENAME,
    TABLES_DIRNAME,
)

if TYPE_CHECKING:
    import pandas as pd

logger = get_logger(__name__)


NO_OTHER_TRIAL = "no other trial within the tolerance"
"""What a recap says in place of an interval that only holds the best trial."""


# ---------------------------------------------------------------------------
# CalibrationReport dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CalibrationReport:
    """Structured summary of one calibration search.

    Returned by ``hmp.calibrate`` and ``Project.calibrate`` for a calibration
    without phases, and kept per phase by a staged one. ``to_dict`` gives the
    same summary as a JSON-friendly mapping.
    """

    session_id: str
    """Id of the session the search belongs to."""

    method: str
    """Optimizer method name (e.g. ``"optuna"``)."""

    n_iterations: int
    """Number of trials actually run (could be < ``max_iter`` if the optimizer converged)."""

    best_objective: float | None
    """Best (minimum) objective value achieved."""

    best_sim_id: str | None
    """Id of the promoted best run when one was written, otherwise ``None``."""

    duration_s: float
    """Wall-clock duration of the search in seconds."""

    save_runs: str
    """The ``save_runs`` mode used (``"none"``, ``"best_n"`` or ``"all"``)."""

    promoted: int
    """Count of trials promoted to runs after the search."""

    best_trial: int | None = None
    """Number of the best trial in ``trials.jsonl``, unique in the session."""

    best_parameters: dict[str, float] | None = None
    """Physical values of the best candidate, keyed by calibrated parameter name.

    ``None`` when no candidate was evaluated. A staged calibration reads it to
    freeze what a phase calibrated."""
    parameter_uncertainty: tuple[Any, ...] = ()
    """Width beside each calibrated value, when the file asked for one.

    Empty unless ``[calibration.uncertainty]`` declared a method that produces it.
    The values themselves are in ``best_parameters`` and are never touched by it."""
    objective_block_fractions: dict[str, Any] | None = None
    """Fraction of the cost each objective block actually took.

    ``"mean"`` averages the fraction over the finished trials (each a mapping of
    block name to its fraction, 0 to 1, of the cost), ``"mean_n_trials"`` is how
    many of them entered that average, and ``"best"`` reads the fraction at the
    reported candidate. ``None`` when the phase scores through a single
    metric with no declared ``[[calibration.objective_blocks]]``, or, for a
    phase reused from a previous run (see ``extra["objective_block_fractions_absent_note"]``
    when that is why), when its journaled trials carry nothing to recompute it
    from. See :func:`hydromodpy.calibration.optim.objective.objective_block_fractions`
    for how a fraction is defined."""
    workspace: Path | None = None
    """Project root the session was written to."""

    best_rel_dir: str | None = None
    """Directory of the promoted best run, relative to the project root
    (``runs/<case>``). ``None`` when nothing was promoted."""

    session_dir: Path | None = None
    """Folder the session journalled its trials in, ``sessions/<case>``."""

    extra: dict[str, Any] = field(default_factory=dict)
    """Free-form metadata (callers may attach anything extra here)."""

    @property
    def iterations(self) -> pd.DataFrame:
        """Return the trial history of the session as a :class:`pandas.DataFrame`.

        Read from ``trials.jsonl``; empty when the report names no session folder.
        """
        import pandas as pd

        if self.session_dir is None:
            return pd.DataFrame()
        return pd.DataFrame(
            [line.model_dump(mode="json") for line in read_trials(self.session_dir)]
        )

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly summary."""
        payload: dict[str, Any] = {
            "session_id": self.session_id,
            "method": self.method,
            "n_iterations": int(self.n_iterations),
            "best_objective": self.best_objective,
            "best_sim_id": self.best_sim_id,
            "duration_s": round(float(self.duration_s), 3),
            "save_runs": self.save_runs,
            "promoted": int(self.promoted),
        }
        if self.best_trial is not None:
            payload["best_trial"] = int(self.best_trial)
        if self.best_parameters is not None:
            payload["best_parameters"] = dict(self.best_parameters)
        if self.parameter_uncertainty:
            payload["parameter_uncertainty"] = [
                item.to_dict() for item in self.parameter_uncertainty
            ]
        if self.objective_block_fractions:
            payload["objective_block_fractions"] = {
                key: (dict(value) if isinstance(value, Mapping) else value)
                for key, value in self.objective_block_fractions.items()
            }
        if self.workspace is not None:
            payload["workspace"] = str(self.workspace)
        if self.best_rel_dir is not None:
            payload["best_rel_dir"] = self.best_rel_dir
        if self.session_dir is not None:
            payload["session_dir"] = str(self.session_dir)
        if self.extra:
            payload["extra"] = dict(self.extra)
        return payload


# ---------------------------------------------------------------------------
# SessionReportData - data handed to the display layer
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SessionReportData:
    """Plain data extracted from one calibration session.

    Carries everything
    :func:`hydromodpy.reporting.calibration_report.render_session` needs to
    produce the HTML report; no live handle on anything. Constructed by
    :func:`load_session_report_data`.

    Attributes
    ----------
    session_id
        Id of the session.
    session_name
        Name of the session directory on disk (``<case>[.vN]``), so the
        report sits under the same name.
    session
        The descriptor as a mapping, plus ``n_iterations``, ``best_objective``
        (the cost of the best trial) and ``phase_name``.
    iterations
        The trials as plain rows, one per trial number.
    workspace_root
        Project root the session was written to.
    best_sim_id
        Id of the promoted best run, or ``None`` when no run was promoted.
    best_rel_dir
        Directory of that run relative to the project root, or ``None``.
    sim_timeseries
        Simulated series of the calibrated variable for the best run (columns
        ``datetime``, ``value``), or ``None`` when no best run is available.
    obs_timeseries
        Observed series (columns ``datetime``, ``value``), or ``None``.
    """

    session_id: str
    session_name: str
    session: dict[str, Any]
    iterations: list[dict[str, Any]]
    workspace_root: Path
    best_sim_id: str | None
    best_rel_dir: str | None
    sim_timeseries: pd.DataFrame | None
    obs_timeseries: pd.DataFrame | None
    variable: str = "discharge"


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


def load_session_report_data(session_dir: Path) -> SessionReportData:
    """Load all data needed to render an HTML report for one session.

    Reads the descriptor, the trial journal, and (when a best run was
    promoted) the simulated and observed series of the calibrated variable
    from the tables of that run. The return value is a plain dataclass, so the
    caller is free to render it through any backend.
    """
    from hydromodpy.calibration.persistence import CalibrationPersistence

    directory = Path(session_dir)
    project_root = directory.parent.parent
    descriptor = read_session(directory)
    persistence = CalibrationPersistence(directory)
    iterations = persistence.load_iterations()
    variable = _calibration_variable(directory)
    best = descriptor.best
    best_rel_dir = best.rel_dir if best is not None else None
    best_sim_id = best.sim_id if best is not None else None
    sim_df = obs_df = None
    if best_rel_dir is not None:
        run_dir = project_root / best_rel_dir
        if variable == "lake_level":
            sim_df, obs_df = _load_best_lake_level(run_dir)
        else:
            sim_df, obs_df = _load_best_discharge(run_dir)
    phases = persistence.phases()
    session_row = descriptor.model_dump(mode="json", by_alias=True)
    session_row["n_iterations"] = len(iterations)
    session_row["best_objective"] = best.objective if best is not None else None
    session_row["phase_name"] = phases[-1].name if phases else None
    return SessionReportData(
        session_id=descriptor.session_id,
        session_name=directory.name,
        session=session_row,
        iterations=iterations,
        workspace_root=project_root,
        best_sim_id=best_sim_id,
        best_rel_dir=best_rel_dir,
        sim_timeseries=sim_df,
        obs_timeseries=obs_df,
        variable=variable,
    )


def _calibration_variable(session_dir: Path) -> str:
    """Return the calibrated variable from the frozen configuration of the session."""
    target = session_dir / SESSION_CONFIG_FILENAME
    if not target.is_file():
        return "discharge"
    with target.open("rb") as handle:
        document = tomllib.load(handle)
    calibration = document.get("calibration")
    if isinstance(calibration, Mapping):
        return str(calibration.get("variable", "discharge"))
    return "discharge"


def _timeseries_table(run_dir: Path) -> pd.DataFrame | None:
    """Return the ``timeseries`` table of a run, or None when the run has none."""
    import pandas as pd

    target = run_dir / TABLES_DIRNAME / f"timeseries{PARQUET_FILE_SUFFIX}"
    if not target.is_file():
        return None
    try:
        return pd.read_parquet(target)
    except (OSError, ValueError) as exc:
        logger.warning("best run series: %s cannot be read: %s", target, exc)
        return None


def _series_of(table: pd.DataFrame, *, variable: str, station: str | None) -> pd.DataFrame | None:
    """Return ``datetime, value`` rows of one variable at one station, or None when empty."""
    rows = table[table["variable"] == variable]
    if station is not None:
        rows = rows[rows["station_id"] == station]
    if rows.empty:
        return None
    ordered = rows.sort_values("timestep") if "timestep" in rows.columns else rows
    return ordered[["time", "value"]].rename(columns={"time": "datetime"}).reset_index(drop=True)


def _load_best_discharge(run_dir: Path) -> tuple[pd.DataFrame | None, pd.DataFrame | None]:
    """Return (simulated, observed) discharge frames of the promoted run."""
    table = _timeseries_table(run_dir)
    if table is None:
        return None, None
    return (
        _series_of(table, variable="discharge", station="_catchment"),
        _series_of(table, variable="discharge_obs", station=None),
    )


def _load_best_lake_level(run_dir: Path) -> tuple[pd.DataFrame | None, pd.DataFrame | None]:
    """Return (simulated stage, observed lake level) of the promoted run.

    The simulated LAK stage is the ``stage`` series of the first ``lake:<id>``
    station of the run. No observed lake level is kept beside the run, so the
    second member is ``None``.
    """
    table = _timeseries_table(run_dir)
    if table is None:
        return None, None
    stages = table[(table["variable"] == "stage") & table["station_id"].str.startswith("lake:")]
    if stages.empty:
        return None, None
    station = str(sorted(stages["station_id"].unique())[0])
    return _series_of(table, variable="stage", station=station), None


def samples_text(samples: Mapping[str, Mapping[str, Any]]) -> str:
    """Return the pairs of ``extra["cost_samples"]`` in words, one clause per output."""
    return scored_samples_text({name: scored_entry(info) for name, info in samples.items()})


def scored_entry(info: Mapping[str, Any]) -> ScoredSamples:
    """Return one ``{n_paired, start, end}`` entry of a report as a :class:`ScoredSamples`."""
    return ScoredSamples(n=info["n_paired"], first=info.get("start"), last=info.get("end"))


def interval_is_degenerate(interval: Mapping[str, Any]) -> bool:
    """Whether an interval holds the best trial alone, so it has no width.

    ``interval`` is a :meth:`ParameterInterval.to_dict` record. Printed as
    ``[x, x]``, such an interval reads as a value known exactly, when it only
    says that no other trial scored within the tolerance.
    """
    n_within = interval.get("n_within")
    if n_within is not None and int(n_within) <= 1:
        return True
    return float(interval["lower"]) == float(interval["upper"])


def promotion_failures(result: Any) -> list[str]:
    """Return the promotions a finished calibration could not write, one line each.

    Reads a calibration report or its ``to_dict`` summary, from one search or
    from a run in phases. A line of a staged run starts with its phase name.
    The search results stay valid: only the replayed runs are missing.
    """
    summary = result.to_dict() if hasattr(result, "to_dict") else result
    if not isinstance(summary, Mapping):
        return []
    phases = summary.get("phases")
    if not isinstance(phases, list):
        phases = [{"phase": None, "report": summary}]
    lines: list[str] = []
    for phase in phases:
        if not isinstance(phase, Mapping):
            continue
        report = phase.get("report")
        extra = report.get("extra") if isinstance(report, Mapping) else None
        failures = extra.get("promotion_failures") if isinstance(extra, Mapping) else None
        name = phase.get("phase")
        for failure in failures or ():
            lines.append(f"phase {name}: {failure}" if name else str(failure))
    if (
        isinstance(summary.get("extra"), Mapping)
        and isinstance(phases, list)
        and summary.get("phases")
    ):
        for failure in summary["extra"].get("promotion_failures") or ():
            lines.append(str(failure))
    return lines


__all__ = (
    "NO_OTHER_TRIAL",
    "CalibrationReport",
    "SessionReportData",
    "interval_is_degenerate",
    "load_session_report_data",
    "promotion_failures",
    "samples_text",
    "scored_entry",
)
