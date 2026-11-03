"""Short factories for the stored documents of a calibration session, in their one-case form."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, date, datetime
from typing import Any

from hydromodpy.results.metric_rule import DateWindow, PeriodWindow
from hydromodpy.results.session.descriptor import (
    BestCase,
    BestTrial,
    ParameterBound,
    SessionCase,
    SessionDescriptor,
)
from hydromodpy.results.session.journal import TrialCase, TrialLine, TrialParam

CASE = "case"
NOW = datetime(2026, 10, 15, 8, 2, 11, tzinfo=UTC)


def calibration_window(start: date, end: date) -> dict[str, PeriodWindow]:
    """Return the ``windows`` table of a search that scores one period."""
    return {"calibration": PeriodWindow(role="calibration", start=start, end=end)}


def best_trial(
    trial: int = 1,
    *,
    cost: float | None = 0.5,
    case: str = CASE,
    sim_id: str | None = None,
    rel_dir: str | None = None,
    parameters: Mapping[str, float] | None = None,
) -> BestTrial:
    """Return the ``best`` of a session of one case."""
    return BestTrial(
        trial=trial,
        cost=cost,
        parameters=dict(parameters or {}),
        cases={case: BestCase(sim_id=sim_id, rel_dir=rel_dir, cost=cost)},
    )


def trial_line(
    trial: int = 1,
    *,
    cost: float | None = 0.5,
    case: str = CASE,
    phase: str = "main",
    restart: int = 0,
    status: str = "completed",
    params: Mapping[str, Any] | None = None,
    components: Mapping[str, float] | None = None,
    params_hash: str | None = None,
    from_cache: bool = False,
    sim_id: str | None = None,
    rel_dir: str | None = None,
    error: str | None = None,
    detail: Mapping[str, Any] | None = None,
    speculative_unused: bool = False,
    started_at: datetime = NOW,
    ended_at: datetime | None = None,
) -> TrialLine:
    """Return one line of a journal of one case; a value in *params* may be a bare number."""
    return TrialLine(
        trial=trial,
        phase=phase,
        restart=restart,
        params={
            name: TrialParam(value=value) if isinstance(value, int | float) else TrialParam(**value)
            for name, value in (params or {"K": 1e-5}).items()
        },
        cost=cost,
        cases={
            case: TrialCase(
                cost=cost,
                components=dict(components or {}),
                status=status,
                params_hash=params_hash,
                from_cache=from_cache,
                sim_id=sim_id,
                rel_dir=rel_dir,
                error=error,
                detail=dict(detail or {}),
            )
        },
        status=status,
        speculative_unused=speculative_unused,
        started_at=started_at,
        ended_at=ended_at,
    )


def joint_trial(trial: int = 1, **fields: Any) -> TrialLine:
    """Return one line of a joint search: costs 0.3 in case ``a`` and 0.5 in case ``b``, total 0.4."""
    line = trial_line(trial, cost=fields.pop("cost", 0.4), **fields)
    cases = {
        name: TrialCase(cost=cost, status="completed", sim_id=None)
        for name, cost in (("a", 0.3), ("b", 0.5))
    }
    return line.model_copy(update={"cases": cases})


def session_descriptor(
    case: str = CASE,
    *,
    site: str | None = None,
    config_hash: str = "c0ffee",
    cost_name: str = "nse",
    best: BestTrial | None = None,
    status: str = "running",
    started_at: datetime = NOW,
    ended_at: datetime | None = None,
    **fields: Any,
) -> SessionDescriptor:
    """Return a descriptor of one case; *fields* are written as they are."""
    return SessionDescriptor(
        session_id=fields.pop("session_id", "s" * 32),
        case_id=case,
        config_hash=config_hash,
        sites=[site] if site else [],
        cases={
            case: SessionCase(
                site=site,
                config_hash=config_hash,
                config_file="config.toml",
                cost_name=cost_name,
                cost_label=fields.get("cost_label"),
            )
        },
        hydromodpy_version=fields.pop("hydromodpy_version", "2.0.0"),
        method=fields.pop("method", "grid"),
        cost_name=cost_name,
        best=best,
        status=status,
        started_at=started_at,
        ended_at=ended_at,
        **fields,
    )


def joint_session(**fields: Any) -> SessionDescriptor:
    """Return a descriptor of a joint search over cases ``a`` (site S1) and ``b`` (site S2).

    The calibration period gives each case its own days; *fields* are written as they are.
    """
    period = PeriodWindow(
        role="calibration",
        start=date(2010, 1, 1),
        end=date(2018, 12, 31),
        by_case={
            "a": DateWindow(start=date(2010, 1, 1), end=date(2014, 12, 31)),
            "b": DateWindow(start=date(2015, 1, 1), end=date(2018, 12, 31)),
        },
    )
    return SessionDescriptor(
        **{
            "session_id": "s" * 32,
            "case_id": "a",
            "config_hash": "h1",
            "sites": ["S1", "S2"],
            "cases": {
                name: SessionCase(
                    site=site, config_hash=f"h{index}", config_file=f"{name}.toml", cost_name="nse"
                )
                for index, (name, site) in enumerate((("a", "S1"), ("b", "S2")), start=1)
            },
            "hydromodpy_version": "2.0.0",
            "method": "tpe",
            "cost_name": "nse",
            "windows": {"calibration": period},
            "started_at": NOW,
            **fields,
        }
    )


def session_opening(case: str = CASE, **overrides: Any) -> dict[str, Any]:
    """Return the keywords of :meth:`CalibrationPersistence.start_session` for one case."""
    return {
        "session_id": "s" * 32,
        "case_id": case,
        "site": None,
        "project": "demo",
        "config_hash": "c0ffee",
        "hydromodpy_version": "2.0.0",
        "method": "grid",
        "cost_name": "nse",
        "bounds": {"K": ParameterBound(lower=1e-6, upper=1e-3, search_space="log")},
        "windows": {},
        **overrides,
    }


__all__ = [
    "CASE",
    "NOW",
    "best_trial",
    "calibration_window",
    "joint_session",
    "joint_trial",
    "session_descriptor",
    "session_opening",
    "trial_line",
]
