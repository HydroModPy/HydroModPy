"""The summary of one calibration session, written once.

What
----
:func:`session_summary` reads a :class:`~hydromodpy.results.session.view.Session`
and returns a :class:`SessionSummary`. :func:`summary_rows` turns it into the
label and text rows that the report page and ``hmp show`` both print.

Why
---
Two readers used to build these rows apart, so a page and the terminal could
disagree. This module is the only writer of the rows (rule 11).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from hydromodpy.results.record.checks import stop_line
from hydromodpy.results.session.descriptor import BestCase, scored_samples_text
from hydromodpy.results.session.journal import TrialParam, on_bound
from hydromodpy.results.session.view import Session
from hydromodpy.results.storage.contract import REPORT_INDEX_FILENAME, RUN_REPORT_DIRNAME

DEFAULT_VARIABLE = "discharge"
"""The calibrated variable of a session whose configuration names none."""

NETWORK_VARIABLE = "network"
"""What an output of support ``network`` calibrates: it reads a map and names no variable."""


@dataclass(frozen=True, slots=True)
class SummaryProfileLine:
    """Time and number of lines of one step kind of the search."""

    kind: str
    name: str
    lines: int
    duration_s: float


@dataclass(frozen=True, slots=True)
class SessionSummary:
    """What a reader needs to know of a session at a glance."""

    name: str
    method: str
    status: str
    trials_by_status: dict[str, int]
    best_trial: int | None
    best_cost: float | None
    cost_label: str | None
    scored_on: str | None
    stop: str | None
    bounds_reached: tuple[str, ...]
    calibrated_variable: str
    """The variables the search was scored on, joined by a comma."""

    report: Path | None
    profile: tuple[SummaryProfileLine, ...]
    project: str = ""
    cost_name: str = ""
    stop_note: str | None = None
    best_sim_id: str | None = None
    started_at: str | None = None
    ended_at: str | None = None
    duration_s: float | None = None
    best_parameters: tuple[str, ...] = ()
    """The value of each parameter at the best trial, as ``K = 0.000124 m/s``."""


def calibrated_variables(config: Mapping[str, object]) -> tuple[str, ...]:
    """Return the variables a session was scored on, in the order its outputs declare them.

    An output names its variable, and one of support ``network`` reads
    :data:`NETWORK_VARIABLE`. A configuration with no output reads its
    ``[calibration] variable``, or :data:`DEFAULT_VARIABLE`.
    """
    calibration = config.get("calibration")
    if not isinstance(calibration, Mapping):
        return (DEFAULT_VARIABLE,)
    outputs = calibration.get("outputs")
    named = [
        NETWORK_VARIABLE if output.get("support") == NETWORK_VARIABLE else output.get("variable")
        for output in (outputs.values() if isinstance(outputs, Mapping) else ())
        if isinstance(output, Mapping)
    ]
    variables = tuple(dict.fromkeys(str(name) for name in named if name))
    return variables or (str(calibration.get("variable", DEFAULT_VARIABLE)),)


NO_UNIT = ("-", "1")
"""How a journal writes the unit of a number without one."""


def _best_parameters(session: Session) -> tuple[str, ...]:
    """Return the value each parameter took at the best trial of the phase that moved it.

    A staged search moves one set of parameters per phase, so the best trial of
    the session holds those of its last phase only. A single search has one best
    trial, which holds them all.
    """
    trials = session.trials
    best = session.descriptor.best
    chosen = [
        trials[(trials["phase"] == phase.name) & (trials["trial"] == phase.best.trial)]
        for phase in session.phases
        if phase.best is not None
    ]
    if not chosen and best is not None:
        chosen = [trials[trials["trial"] == best.trial]]
    found: dict[str, str] = {}
    for rows in chosen:
        if not rows.empty:
            for name, payload in (rows.iloc[0]["parameters"] or {}).items():
                found[name] = _parameter_text(name, payload)
    return tuple(found.values())


def _parameter_text(name: str, payload: object) -> str:
    """Return one journaled parameter as its name, its value and its unit."""
    if isinstance(payload, TrialParam):
        payload = payload.model_dump(exclude_defaults=True)
    value, units = (
        (payload.get("value"), payload.get("units"))
        if isinstance(payload, Mapping)
        else (payload, None)
    )
    return f"{name} = {float(value):.6g}" + ("" if not units or units in NO_UNIT else f" {units}")


def session_summary(session: Session) -> SessionSummary:
    """Read the summary of a session from its directory."""
    descriptor = session.descriptor
    trials = session.trials
    by_trial = trials.drop_duplicates("trial")
    counts = by_trial["status"].value_counts().to_dict()
    best = descriptor.best
    reached: tuple[str, ...] = ()
    if best is not None:
        rows = trials[trials["trial"] == best.trial]
        if not rows.empty:
            payloads = rows.iloc[0]["parameters"] or {}
            reached = tuple(sorted(name for name, payload in payloads.items() if on_bound(payload)))
    page = session.dir / RUN_REPORT_DIRNAME / REPORT_INDEX_FILENAME
    profile = session.profile()
    started, ended = descriptor.started_at, descriptor.ended_at
    return SessionSummary(
        name=session.name,
        method=descriptor.method,
        status=descriptor.status,
        trials_by_status={str(key): int(value) for key, value in sorted(counts.items())},
        best_trial=None if best is None else best.trial,
        best_cost=None if best is None else best.cost,
        cost_label=descriptor.cost_label,
        scored_on=_scored_on(session),
        stop=None
        if descriptor.stop_state is None
        else stop_line(descriptor.stop_state, descriptor.stopping_rule),
        bounds_reached=reached,
        calibrated_variable=", ".join(calibrated_variables(session.config)),
        report=page if page.is_file() else None,
        profile=tuple(
            SummaryProfileLine(row.kind, row.name, int(row.lines), float(row.duration_s))
            for row in profile.itertuples()
        ),
        project=session.dir.parent.parent.name,
        cost_name=descriptor.cost_name,
        stop_note=descriptor.stop_note,
        best_sim_id=None if best is None else _best_runs(best.cases),
        started_at=started.isoformat(),
        ended_at=None if ended is None else ended.isoformat(),
        duration_s=None if ended is None else (ended - started).total_seconds(),
        best_parameters=_best_parameters(session),
    )


def _best_runs(cases: Mapping[str, BestCase]) -> str | None:
    """Return the run of the best trial, ``case: run`` per case when there are several."""
    runs = {case_id: case.sim_id for case_id, case in cases.items() if case.sim_id}
    if len(runs) == 1 and len(cases) == 1:
        return next(iter(runs.values()))
    return ", ".join(f"{case_id}: {sim_id}" for case_id, sim_id in runs.items()) or None


def summary_rows(summary: SessionSummary) -> list[tuple[str, str]]:
    """Return the label and the text of each summary row of a session."""
    rows: list[tuple[str, str]] = [("session", summary.name)]
    if summary.project:
        rows.append(("project", summary.project))
    rows += [
        ("method", summary.method),
        ("status", summary.status),
        ("trials", ", ".join(f"{n} {k}" for k, n in summary.trials_by_status.items()) or "none"),
    ]
    if summary.best_trial is not None:
        cost = "not scored" if summary.best_cost is None else f"{summary.best_cost:.6g}"
        if summary.cost_label and summary.best_cost is not None:
            # A cost of 0.08 on an NSE reads as a poor score; the label says it is 1 - NSE.
            cost += f" ({summary.cost_label})"
        rows.append(("best trial", f"{summary.best_trial}, cost {cost}"))
    if summary.best_parameters:
        rows.append(("best parameters", ", ".join(summary.best_parameters)))
    if summary.cost_name:
        rows.append(("cost name", summary.cost_name))
    if summary.best_sim_id:
        rows.append(("best run", summary.best_sim_id))
    if summary.scored_on:
        rows.append(("scored on", summary.scored_on))
    if summary.stop:
        rows.append(("search stopped", summary.stop))
    if summary.stop_note:
        rows.append(("stop note", summary.stop_note))
    if summary.started_at:
        rows.append(("started", summary.started_at))
    if summary.ended_at:
        rows.append(("ended", summary.ended_at))
    if summary.duration_s is not None:
        rows.append(("duration", f"{summary.duration_s:.1f} s"))
    rows.append(("calibrated variable", summary.calibrated_variable))
    rows.append(
        (
            "bounds reached",
            ", ".join(summary.bounds_reached) if summary.bounds_reached else "none",
        )
    )
    if summary.profile:
        total = sum(line.duration_s for line in summary.profile)
        rows.append(("profile", f"{total:.1f} s over {len(summary.profile)} step kind(s)"))
    return rows


def _scored_on(session: Session) -> str | None:
    """Return the pairs the best cost was scored on, and the window the session declares."""
    descriptor = session.descriptor
    window = next(iter(descriptor.windows.values()), None)
    declared = f"window {window.start} to {window.end}" if window else None
    if descriptor.scored:
        text = f"{scored_samples_text(descriptor.scored)}, best trial"
        return text + (f" ({declared})" if declared else "")
    if declared:
        return f"{declared}, pairs not counted"
    return None


__all__ = (
    "DEFAULT_VARIABLE",
    "NETWORK_VARIABLE",
    "SessionSummary",
    "SummaryProfileLine",
    "calibrated_variables",
    "session_summary",
    "summary_rows",
)
