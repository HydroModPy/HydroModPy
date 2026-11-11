"""The label of a run is a function of reading, not a value of the seal.

Why
---
A seal says what was measured (:mod:`hydromodpy.results.record.checks`). Whether
those facts make a run ``calibrated`` depends on rules that change, and on
bugs found after the run was sealed. So the label is computed here, every
time it is read, from the checks, the version that produced the run and the
bugs of the register of changes shipped with this build. An old run is reclassified
by a newer build without anyone rewriting its files.

Labels, in order of precedence
------------------------------
1. ``failed``: a fatal validity failed. The numbers are a fiction.
2. ``failed``: ``checks.converged`` is ``False``, with the reason
   ``solver did not converge``. Unknown convergence (``None``) is not a
   failure.
3. ``exploratory`` with the bug ids: a known bug of the producing version
   touches a quantity of the run. The run is declassed, whatever else it is.
4. ``evaluated``: the run is calibrated (rule 5 holds) and was scored, with
   at least ``ValidityRules.min_scored_samples`` samples, on a window that
   shares no day with the windows the session scored (``calibrated_by.windows``,
   bounds included). It is a split-sample: the calibrated parameters judged on
   days the search never saw. A window that overlaps the calibration window
   without being equal to it keeps the run ``calibrated``, with a reason that
   says so. A session window that was not recorded cannot be told apart, so
   the run stays ``calibrated``.
5. ``calibrated``: the run was promoted by a session whose status is one of
   ``ValidityRules.calibrated_session_statuses`` (``completed`` only, by
   default), the solver did not report a failed convergence, and a window was
   scored. A scored window is a period of role ``calibration`` in
   ``calibrated_by.windows``, or the headline window with at least
   ``min_scored_samples`` samples, or the single state of a steady run whose
   cost the session read (``flow_regime`` is ``steady`` and
   ``calibrated_by.cost`` is finite). A steady run is sealed without a score
   window and with no sample, so the cost stands for them. A promoted run with
   no scored window is ``exploratory``, with the reason ``no_scored_window``.
6. ``exploratory``: anything else. A run scored on its own window without a
   promoting session stays here, with the reason ``not_promoted``: a score
   alone does not qualify a run.

A parameter that ended on a bound of its range (``checks.bounds_hit``) adds the
reason ``bound_reached`` to any label, last. It does not change the label.

A reason is a :class:`Reason`, a code of :data:`REASON_CODES` with the values
its phrase needs. Its sentence is read from ``phrases.toml``
(:func:`hydromodpy.schema.phrases.phrase`), in English or in French, so the
same label reads in both languages.

The water budget is not a label: ``checks.budget_pct`` stays a column, and
only a failed *fatal* validity (which the calibration raises on a budget it
rejects) reaches the label.

Why the search stopped (``calibrated_by.stop_state``) is not a label either.
It reaches the label through the session status alone: a search stopped by
its budget before a rule of its own closes its session ``partial``, so its
run is ``exploratory`` (rule 6), never ``failed``, since its numbers are
those of a solved model. A search with no rule of its own that spent its
budget closes ``completed``, so its run is ``calibrated`` (rule 5), and the
run README says why its search stopped.

The known issues are the bugs of the register
----------------------------------------------
The register is ``hydromodpy/schema/changes.toml``, read by
:mod:`hydromodpy.schema.changes`. One ``[[bug]]`` per fix that changes a number::

    [[bug]]
    id = "discharge_scores_before_period_alignment"  # [a-z0-9_]+, stable
    since = "2.0.0"  # the first version with the fix
    versions = "<2.0.0a1"  # PEP 440 specifier set of the affected versions
    quantities = ["metrics"]  # tokens a run exposes, see run_quantities()
    text = "..."  # one sentence a reader can act on
    commit = "e6c5e50f5"  # the commit that fixed it, optional

A run exposes its quantities as tokens: ``metrics`` when it carries a
score, ``heads@<solver>`` and ``fluxes@<solver>`` for its solver,
``mesh@<engine>`` for its mesh engine, ``derived@<version>`` for the rules its
seal stamps as ``derive_rule_version``, and ``source@<section>_<source>`` for each
``[[data.<section>.sources]]`` its ``config.toml`` declares. A bug hits a run when
its versions contain the run's ``hydromodpy_version`` and one of its quantities is
one of the run's. A fix lands with its row. The derived fields are rebuilt on read,
so a fix of one changes what an old run reads: the fix bumps
``DERIVE_RULE_VERSION`` and its row names ``derived@<old version>``.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Annotated, Final

from pydantic import Field

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.stored import Vocabulary
from hydromodpy.results.metric_rule import CALIBRATION_ROLE, DateWindow
from hydromodpy.results.record.checks import CalibrationSessionStatus, Checks
from hydromodpy.schema.changes import REGISTER, Bug
from hydromodpy.schema.phrases import keys, phrase

RULE_VERSION: Final[str] = "3"
"""Version of the labeling rules. Bump it when a label changes meaning."""

Label = Annotated[str, Vocabulary("exploratory", "calibrated", "evaluated", "failed")]
"""What a reader may call a run today."""

CALIBRATED_LABELS: Final[tuple[Label, ...]] = ("calibrated", "evaluated")
"""Labels of a calibrated run: an evaluated run is calibrated, scored out of its window."""

RESTART_START: Final = "start@restart_from"
"""Token of a run that starts from an earlier one by ``[flow] restart_from``."""

CYCLIC_LAKE_START: Final = "start@spinup_cyclic_lake"
"""Token of a cyclic spin-up beside a declared lake."""


class ValidityRules(HydroModelBase):
    """The rules :func:`label_for` applies, documented and versioned."""

    rule_version: str = Field(default=RULE_VERSION, description="Version of these rules")
    calibrated_session_statuses: list[CalibrationSessionStatus] = Field(
        default_factory=lambda: ["completed"],
        description="Session statuses under which a promoted run is calibrated",
    )
    min_scored_samples: int = Field(
        default=1, ge=1, description="Samples a score needs for the run to be evaluated"
    )
    declass_on_known_issue: bool = Field(
        default=True, description="Whether a known bug of the producing version declasses a run"
    )


REASON_CODES: Final[frozenset[str]] = keys("label_reason")
"""The closed set of reason codes, the keys of ``[label_reason]`` in ``phrases.toml``."""

STEADY_REGIME: Final[str] = "steady"
"""The flow regime of a run with one state, scored by its cost alone."""


@dataclass(frozen=True, slots=True)
class Reason:
    """Why a run has its label: a code of :data:`REASON_CODES` and the values of its phrase."""

    code: str
    values: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if self.code not in REASON_CODES:
            known = ", ".join(sorted(REASON_CODES))
            raise ValueError(f"reason code {self.code!r} is not one of {known}")

    @classmethod
    def of(cls, code: str, **values: object) -> Reason:
        """Return the reason *code* with its values, each written as text."""
        return cls(code, tuple((name, str(value)) for name, value in values.items()))

    def text(self, lang: str = "en") -> str:
        """Return the sentence of the reason in *lang*."""
        return phrase("label_reason", self.code, lang, **dict(self.values))


@dataclass(frozen=True, slots=True)
class LabelResult:
    """A label, the rules it came from and why."""

    label: Label
    rule_version: str
    causes: tuple[Reason, ...]
    known_issues: tuple[str, ...]

    def texts(self, lang: str = "en") -> tuple[str, ...]:
        """Return the sentence of each reason in *lang*, in order."""
        return tuple(cause.text(lang) for cause in self.causes)

    @property
    def reasons(self) -> tuple[str, ...]:
        """The reasons in English, as the index and the README of a run print them."""
        return self.texts("en")


def known_issues_hitting(
    hydromodpy_version: str,
    quantities: Sequence[str],
    issues: Sequence[Bug] | None = None,
) -> tuple[Bug, ...]:
    """Return the bugs that touch a run of that version exposing those quantities."""
    register = REGISTER.bugs if issues is None else tuple(issues)
    return tuple(bug for bug in register if bug.hits(hydromodpy_version, quantities))


def run_quantities(
    *,
    solver: str,
    mesh_engine: str | None = None,
    has_metrics: bool = False,
    derive_rule_version: str | None = None,
    sources: Sequence[str] = (),
    starts: Sequence[str] = (),
) -> tuple[str, ...]:
    """Return the quantity tokens a run exposes, the vocabulary of the register.

    *sources* are the ``source@<section>_<source>`` tokens of the sources the run
    declares (:func:`hydromodpy.schema.sources.declared_source_tokens`). *starts*
    are the ``start@<kind>`` tokens of how its heads start
    (:func:`hydromodpy.results.record.label.declared_start_tokens`).
    """
    tokens = [f"heads@{solver}", f"fluxes@{solver}"]
    if mesh_engine:
        tokens.append(f"mesh@{mesh_engine}")
    if has_metrics:
        tokens.append("metrics")
    if derive_rule_version:
        tokens.append(f"derived@{derive_rule_version}")
    tokens.extend(sources)
    tokens.extend(starts)
    return tuple(tokens)


def _share_a_day(first: DateWindow, second: DateWindow) -> bool:
    """Return whether two closed windows have a day in common."""
    return first.start <= second.end and second.start <= first.end


def label_for(
    checks: Checks,
    *,
    hydromodpy_version: str,
    quantities: Sequence[str] = (),
    flow_regime: str | None = None,
    rules: ValidityRules | None = None,
    issues: Sequence[Bug] | None = None,
) -> LabelResult:
    """Return the label of a run today, with the reasons.

    *flow_regime* is ``run.flow_regime`` of the seal; a steady run is scored by
    the cost of its session. *issues* overrides the bugs of the shipped
    register, for a caller that reads another build's register or a test. The
    rules are those of the module docstring.
    """
    active = ValidityRules() if rules is None else rules
    label, causes, known = _label(
        checks, hydromodpy_version, quantities, flow_regime, active, issues
    )
    if checks.bounds_hit:
        causes = (*causes, Reason.of("bound_reached", names=", ".join(checks.bounds_hit)))
    return LabelResult(label, active.rule_version, causes, known)


def _label(
    checks: Checks,
    hydromodpy_version: str,
    quantities: Sequence[str],
    flow_regime: str | None,
    active: ValidityRules,
    issues: Sequence[Bug] | None,
) -> tuple[Label, tuple[Reason, ...], tuple[str, ...]]:
    """Return the label, its reasons and the known issues, before the bound reason."""
    if checks.fatal_failed():
        failed = [v.name for v in checks.failed_validities() if v.fatal]
        return "failed", (Reason.of("fatal_validity", names=", ".join(failed)),), ()
    if checks.converged is False:
        return "failed", (Reason.of("not_converged"),), ()
    hitting: tuple[Bug, ...] = ()
    if active.declass_on_known_issue:
        hitting = known_issues_hitting(hydromodpy_version, quantities, issues)
    if hitting:
        return (
            "exploratory",
            tuple(
                Reason.of("known_issue", id=issue.id, version=hydromodpy_version, text=issue.text)
                for issue in hitting
            ),
            tuple(issue.id for issue in hitting),
        )
    by = checks.calibrated_by
    window = checks.score_window
    samples = checks.n_samples or 0
    scored = window is not None and samples >= active.min_scored_samples
    if by is not None and by.session_status in active.calibrated_session_statuses:
        promoted = Reason.of("promoted", session_id=by.session_id, status=by.session_status)
        searched = [
            DateWindow(start=period.start, end=period.end)
            for period in by.windows.values()
            if period.role == CALIBRATION_ROLE
        ]
        steady = flow_regime == STEADY_REGIME and by.cost is not None and math.isfinite(by.cost)
        if not (searched or scored or steady):
            return "exploratory", (promoted, Reason.of("no_scored_window")), ()
        if scored and searched and window not in searched:
            assert window is not None
            span = {
                "start": min(p.start for p in searched),
                "end": max(p.end for p in searched),
                "window_start": window.start,
                "window_end": window.end,
                "samples": samples,
            }
            if any(_share_a_day(window, period) for period in searched):
                return "calibrated", (promoted, Reason.of("overlaps_calibration", **span)), ()
            return "evaluated", (promoted, Reason.of("scored_outside_calibration", **span)), ()
        return "calibrated", (promoted,), ()
    reasons: list[Reason] = []
    if by is not None:
        reasons.append(
            Reason.of("session_ended", session_id=by.session_id, status=by.session_status)
        )
    if window is None:
        reasons.append(Reason.of("no_score_window"))
    elif not scored:
        reasons.append(Reason.of("too_few_samples", samples=samples))
    elif by is None:
        reasons.append(Reason.of("not_promoted", window_start=window.start, window_end=window.end))
    return "exploratory", tuple(reasons), ()


__all__ = [
    "CALIBRATED_LABELS",
    "CYCLIC_LAKE_START",
    "REASON_CODES",
    "RESTART_START",
    "RULE_VERSION",
    "STEADY_REGIME",
    "Label",
    "LabelResult",
    "Reason",
    "ValidityRules",
    "known_issues_hitting",
    "label_for",
    "run_quantities",
]
