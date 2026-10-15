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
from typing import Any, Final, Literal

from pydantic import Field

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.results.metric_rule import DateWindow

CHECKS_SCHEMA: Final[str] = "hydromodpy.checks.v1"
"""Schema id of the block, the name of its JSON Schema file."""

CalibrationSessionStatus = Literal["completed", "partial", "aborted"]
"""How the session that promoted a run ended."""


@dataclass(frozen=True)
class Validity:
    """One check that qualifies a result without penalising it.

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
    window: DateWindow | None = Field(
        default=None, description="Window the session scored its objective on"
    )


class Checks(HydroModelBase):
    """The measured facts of a run, sealed with it."""

    budget_pct: float | None = Field(default=None, description="Water-budget discrepancy, percent")
    budget_threshold_pct: float | None = Field(
        default=None, description="Discrepancy the user accepts, percent; none when undeclared"
    )
    converged: bool | None = Field(default=None, description="Convergence reported by the solver")
    obs_coverage: float | None = Field(
        default=None, ge=0.0, le=1.0, description="Share of the score window with observations"
    )
    score_window: DateWindow | None = Field(
        default=None, description="Window the run was scored on"
    )
    n_samples: int | None = Field(default=None, ge=0, description="Samples the score used")
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
        by_window = None if by is None else by.window
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
            "validities_failed": ",".join(v.name for v in failed) if failed else None,
            "fatal_failed": self.fatal_failed(),
            "bounds_hit": ",".join(self.bounds_hit) if self.bounds_hit else None,
            "code_reproducible": self.code_reproducible,
        }


__all__ = ["CHECKS_SCHEMA", "CalibratedBy", "CalibrationSessionStatus", "Checks", "Validity"]
