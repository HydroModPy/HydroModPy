"""The ``checks`` block of a seal: the facts a label is derived from.

Why
---
A run is not valid or invalid at seal time. What is sealed is what was
measured: the water-budget discrepancy and the threshold the user declared,
the convergence, the coverage of the score window, the verdicts of the
calibration criteria and the session that promoted the run. The label
(``exploratory``, ``calibrated``, ``evaluated``, ``failed``) is computed from
these facts by :mod:`hydromodpy.results.validity_rules` every time it is read,
so a rule that changes, or a bug found later, reclassifies a run without
rewriting its seal.

Format
------
``manifest.json`` carries the block as :class:`Checks`; ``simulation.parquet``
carries it flat, one column per fact, under the names of :meth:`Checks.flatten`
(the ``CHECK_COLUMNS`` of :mod:`hydromodpy.results.storage.parquet_schemas`).
A :class:`Validity` is the verdict of one criterion, copied as the calibration
produced it: a name, a pass or fail, the value, a sentence, and whether a
failure makes the number a fiction rather than coarse.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any, Final

from pydantic import ConfigDict, Field, field_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.stored import Vocabulary
from hydromodpy.core.io.document_version import VersionWindow
from hydromodpy.results.metric_rule import DateWindow, PeriodWindow, calibration_extent

CHECKS_SCHEMA: Final[str] = "hydromodpy.checks.v2"
"""Schema id of the block, the name of its JSON Schema file."""

CHECKS_VERSIONS: Final[VersionWindow] = VersionWindow(
    oldest="hydromodpy.checks.v2", current=CHECKS_SCHEMA
)
"""Versions of the block this code reads."""

CalibrationSessionStatus = Annotated[str, Vocabulary("completed", "partial", "aborted")]
"""How the session that promoted a run ended."""

StopState = Annotated[str, Vocabulary("rule_met", "plan_exhausted", "budget_spent")]
"""Why a search stopped.

``rule_met``: the engine's own stopping rule was met. ``plan_exhausted``: every
point an engine planned up front (a grid, a Latin hypercube) was solved.
``budget_spent``: the budget ended first, or the engine stopped proposing
before its rule was met. Only the first two are convergence.
"""

BUDGET_RULE: Final[str] = "budget"
"""The rule of an engine that declares none of its own: it stops on max_trials."""


FROZE_BUDGET_ONLY: Final[str] = "froze the best of a budget-only search"
"""What a phase says when it passes on the best trial of a search with no rule of its own."""


def stop_text(state: StopState | None, rule: str | None) -> str:
    """Return why a search stopped, in words, from its state and its rule."""
    if state == "rule_met":
        return f"met its own rule ({rule})"
    if state == "plan_exhausted":
        return f"exhausted its plan ({rule} solved)"
    if state == "budget_spent" and rule == BUDGET_RULE:
        return "spent its budget, a budget-only search with no rule of its own"
    if state == "budget_spent":
        return f"spent its budget before its rule ({rule}) was met"
    return "not recorded" if state is None else f"stopped as {state}"


def stop_line(state: StopState | None, rule: str | None) -> str:
    """Return why a search stopped and whether that is convergence, in words."""
    if state is None:
        return stop_text(state, rule)
    verdict = "converged" if state in ("rule_met", "plan_exhausted") else "not converged"
    return f"{stop_text(state, rule)}, {verdict}"


@dataclass(frozen=True)
class Validity:
    """One check that qualifies a result without penalizing it.

    ``passed`` is the verdict, ``message`` the sentence a reader who is not a
    hydrogeologist needs. ``fatal`` is true for the few checks whose failure
    makes the number a fiction rather than coarse.
    """

    name: str
    passed: bool
    value: float | None
    message: str
    fatal: bool = False


class CalibratedBy(HydroModelBase):
    """The session, phase and trial a promoted run comes from."""

    session_id: str = Field(description="Session that promoted the run")
    phase: str | None = Field(default=None, description="Phase of that session")
    trial: int = Field(ge=1, description="Trial number, unique in the session")
    session_status: CalibrationSessionStatus = Field(description="How the session ended")
    stop_state: StopState | None = Field(
        default=None,
        description="Why the search of that phase stopped: rule_met, plan_exhausted or "
        "budget_spent; none when not recorded",
    )
    stopping_rule: str | None = Field(
        default=None,
        description="The rule that search stops on, 'budget' for one with no rule of its own",
    )
    metric: str | None = Field(default=None, description="Name of the cost of the case of this run")
    cost: float | None = Field(
        default=None,
        description="Cost of the case of this run at that trial, never the total of a joint "
        "search; null when the search keeps no single cost",
    )
    validation_cost: float | None = Field(
        default=None,
        description="Score of that trial on the validation period, in the sense of the cost; "
        "null when it has none",
    )
    windows: dict[str, PeriodWindow] = Field(
        default_factory=dict,
        description="Periods of the search as the case of this run read them, by name",
    )


class Checks(HydroModelBase):
    """The measured facts of a run, sealed with it."""

    model_config = ConfigDict(populate_by_name=True)

    schema_: str = Field(default=CHECKS_SCHEMA, alias="schema", description="Schema id")

    @field_validator("schema_")
    @classmethod
    def _read_here(cls, value: str) -> str:
        if not CHECKS_VERSIONS.holds(value):
            raise ValueError(f"schema is {value!r}, this module reads {CHECKS_SCHEMA!r}")
        return value

    budget_pct: float | None = Field(default=None, description="Water-budget discrepancy, percent")
    budget_threshold_pct: float | None = Field(
        default=None, description="Discrepancy the user accepts, percent; none when undeclared"
    )
    converged: bool | None = Field(default=None, description="Convergence reported by the solver")
    obs_coverage: float | None = Field(
        default=None, ge=0.0, le=1.0, description="Share of the score window with observations"
    )
    score_window: DateWindow | None = Field(
        default=None, description="Window of the headline score, one by definition"
    )
    n_samples: int | None = Field(default=None, ge=0, description="Samples the headline score used")
    calibrated_by: CalibratedBy | None = Field(
        default=None, description="Present on a run promoted by a calibration"
    )
    validities: list[Validity] = Field(default_factory=list, description="Criterion verdicts")
    bounds_hit: list[str] = Field(
        default_factory=list, description="Calibrated parameters that ended on a bound"
    )
    code_reproducible: bool | None = Field(
        default=None, description="False for a dirty checkout or an editable install"
    )

    def failed_validities(self) -> tuple[Validity, ...]:
        """Return the validities that did not pass, in order."""
        return tuple(v for v in self.validities if not v.passed)

    def fatal_failed(self) -> bool:
        """Return whether a fatal validity failed."""
        return any(v.fatal for v in self.failed_validities())

    def flatten(self) -> dict[str, Any]:
        """Return the block as one flat row, the columns of ``simulation.parquet``."""
        failed = self.failed_validities()
        by = self.calibrated_by
        by_window = None if by is None else calibration_extent(by.windows)
        return {
            "budget_pct": self.budget_pct,
            "budget_threshold_pct": self.budget_threshold_pct,
            "converged": self.converged,
            "obs_coverage": self.obs_coverage,
            "score_window_start": None if self.score_window is None else self.score_window.start,
            "score_window_end": None if self.score_window is None else self.score_window.end,
            "n_samples": self.n_samples,
            "calibrated_by_session_id": None if by is None else by.session_id,
            "calibrated_by_phase": None if by is None else by.phase,
            "calibrated_by_trial": None if by is None else by.trial,
            "calibrated_by_session_status": None if by is None else by.session_status,
            "calibrated_by_window_start": None if by_window is None else by_window.start,
            "calibrated_by_window_end": None if by_window is None else by_window.end,
            "calibrated_by_metric": None if by is None else by.metric,
            "calibrated_by_cost": None if by is None else by.cost,
            "validities_failed": ",".join(v.name for v in failed) if failed else None,
            "fatal_failed": self.fatal_failed(),
            "bounds_hit": ",".join(self.bounds_hit) if self.bounds_hit else None,
            "code_reproducible": self.code_reproducible,
        }


__all__ = [
    "BUDGET_RULE",
    "CHECKS_SCHEMA",
    "CHECKS_VERSIONS",
    "CalibratedBy",
    "CalibrationSessionStatus",
    "Checks",
    "FROZE_BUDGET_ONLY",
    "StopState",
    "Validity",
    "stop_line",
    "stop_text",
]
