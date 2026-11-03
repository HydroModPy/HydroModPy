"""The label of a run is a function of reading, not a value of the seal.

Why
---
A seal says what was measured (:mod:`hydromodpy.results.checks`). Whether
those facts make a run ``calibrated`` depends on rules that change, and on
bugs found after the run was sealed. So the label is computed here, every
time it is read, from the checks, the version that produced the run and the
register of known issues shipped with this build. An old run is reclassified
by a newer build without anyone rewriting its files.

Labels, in order of precedence
------------------------------
1. ``failed``: a fatal validity failed. The numbers are a fiction.
2. ``failed``: ``checks.converged`` is ``False``, with the reason
   ``solver did not converge``. Unknown convergence (``None``) is not a
   failure.
3. ``exploratory`` with the issue ids: a known issue of the producing version
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
   default), and the solver did not report a failed convergence.
6. ``exploratory``: anything else. A run scored on its own window without a
   promoting session stays here, with the reason ``scored on ..., not promoted
   by a session``: a score alone does not qualify a run.

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

Format of ``known_issues.toml``
-------------------------------
The register ships in the wheel next to this module and is read with
``importlib.resources``. One ``[[issue]]`` table per issue::

    [[issue]]
    id = "discharge_scores_before_period_alignment"  # [a-z0-9_]+, stable
    versions = "<2.0.0a1"  # PEP 440 specifier set of the affected versions
    quantities = ["metrics"]  # tokens a run exposes, see run_quantities()
    since_commit = "e6c5e50f5"  # the commit that fixed it
    description = "..."  # one sentence a reader can act on

A run exposes its quantities as tokens: ``metrics`` when it carries a
score, ``heads@<solver>`` and ``fluxes@<solver>`` for its solver,
``mesh@<engine>`` for its mesh engine, ``derived@<version>`` for the rules its
seal stamps as ``derive_rule_version``. An issue hits a run when its versions
contain the run's ``hydromodpy_version`` and one of its quantities is one of
the run's. The register is a feature: a fix lands with its entry. The derived
fields are rebuilt on read, so a fix of one changes what an old run reads: the fix
bumps ``DERIVE_RULE_VERSION`` and its entry names ``derived@<old version>``.
"""

from __future__ import annotations

import tomllib
from collections.abc import Sequence
from dataclasses import dataclass
from importlib.resources import files
from typing import Annotated, Final

from packaging.specifiers import SpecifierSet
from packaging.version import Version
from pydantic import Field

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.stored import Vocabulary
from hydromodpy.results.checks import CalibrationSessionStatus, Checks
from hydromodpy.results.metric_rule import CALIBRATION_ROLE, DateWindow

RULE_VERSION: Final[str] = "2"
"""Version of the labeling rules. Bump it when a label changes meaning."""

KNOWN_ISSUES_FILENAME: Final[str] = "known_issues.toml"
"""The register of known issues, package data of this module."""

Label = Annotated[str, Vocabulary("exploratory", "calibrated", "evaluated", "failed")]
"""What a reader may call a run today."""

CALIBRATED_LABELS: Final[tuple[Label, ...]] = ("calibrated", "evaluated")
"""Labels of a calibrated run: an evaluated run is calibrated, scored out of its window."""


class KnownIssue(HydroModelBase):
    """One bug that declasses the runs of the versions it touched."""

    id: str = Field(pattern=r"^[a-z0-9_]+$", description="Stable id of the issue")
    versions: str = Field(description="PEP 440 specifier set of the affected versions")
    quantities: list[str] = Field(min_length=1, description="Run quantities the issue touches")
    since_commit: str = Field(description="Commit that fixed the issue")
    description: str = Field(description="What was wrong, in one sentence")

    def hits(self, hydromodpy_version: str, quantities: Sequence[str]) -> bool:
        """Return whether the issue touches a run of *hydromodpy_version* exposing *quantities*."""
        version = Version(hydromodpy_version)
        affected = SpecifierSet(self.versions, prereleases=True)
        return version in affected and bool(set(self.quantities) & set(quantities))


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
        default=True, description="Whether a known issue of the producing version declasses a run"
    )


@dataclass(frozen=True, slots=True)
class LabelResult:
    """A label, the rules it came from and why."""

    label: Label
    rule_version: str
    reasons: tuple[str, ...]
    known_issues: tuple[str, ...]


def load_known_issues() -> tuple[KnownIssue, ...]:
    """Return the register shipped with this build."""
    text = files(__package__).joinpath(KNOWN_ISSUES_FILENAME).read_text(encoding="utf-8")
    payload = tomllib.loads(text)
    issues = tuple(KnownIssue.model_validate(entry) for entry in payload.get("issue", ()))
    ids = [issue.id for issue in issues]
    if len(ids) != len(set(ids)):
        raise ValueError(f"{KNOWN_ISSUES_FILENAME} repeats an issue id: {sorted(ids)}")
    return issues


def known_issues_hitting(
    hydromodpy_version: str,
    quantities: Sequence[str],
    issues: Sequence[KnownIssue] | None = None,
) -> tuple[KnownIssue, ...]:
    """Return the issues that touch a run of that version exposing those quantities."""
    register = load_known_issues() if issues is None else tuple(issues)
    return tuple(issue for issue in register if issue.hits(hydromodpy_version, quantities))


def run_quantities(
    *,
    solver: str,
    mesh_engine: str | None = None,
    has_metrics: bool = False,
    derive_rule_version: str | None = None,
) -> tuple[str, ...]:
    """Return the quantity tokens a run exposes, the vocabulary of the register."""
    tokens = [f"heads@{solver}", f"fluxes@{solver}"]
    if mesh_engine:
        tokens.append(f"mesh@{mesh_engine}")
    if has_metrics:
        tokens.append("metrics")
    if derive_rule_version:
        tokens.append(f"derived@{derive_rule_version}")
    return tuple(tokens)


def _share_a_day(first: DateWindow, second: DateWindow) -> bool:
    """Return whether two closed windows have a day in common."""
    return first.start <= second.end and second.start <= first.end


def label_for(
    checks: Checks,
    *,
    hydromodpy_version: str,
    quantities: Sequence[str] = (),
    rules: ValidityRules | None = None,
    issues: Sequence[KnownIssue] | None = None,
) -> LabelResult:
    """Return the label of a run today, with the reasons.

    *issues* overrides the shipped register, for a caller that reads another
    build's register or a test. The rules are those of the module docstring.
    """
    active = ValidityRules() if rules is None else rules
    if checks.fatal_failed():
        failed = [v.name for v in checks.failed_validities() if v.fatal]
        return LabelResult(
            "failed",
            active.rule_version,
            (f"fatal validity failed: {', '.join(failed)}",),
            (),
        )
    if checks.converged is False:
        return LabelResult("failed", active.rule_version, ("solver did not converge",), ())
    hitting: tuple[KnownIssue, ...] = ()
    if active.declass_on_known_issue:
        hitting = known_issues_hitting(hydromodpy_version, quantities, issues)
    if hitting:
        return LabelResult(
            "exploratory",
            active.rule_version,
            tuple(
                f"known issue {issue.id} touches {hydromodpy_version}: {issue.description}"
                for issue in hitting
            ),
            tuple(issue.id for issue in hitting),
        )
    by = checks.calibrated_by
    window = checks.score_window
    scored = window is not None and (checks.n_samples or 0) >= active.min_scored_samples
    if by is not None and by.session_status in active.calibrated_session_statuses:
        promoted = f"promoted by session {by.session_id}, {by.session_status}"
        searched = [
            DateWindow(start=period.start, end=period.end)
            for period in by.windows.values()
            if period.role == CALIBRATION_ROLE
        ]
        if scored and searched and window not in searched:
            assert window is not None
            scoring = f"scored on {window.start} to {window.end} with {checks.n_samples} samples"
            start, end = min(p.start for p in searched), max(p.end for p in searched)
            calibration = f"the calibration window {start} to {end}"
            if any(_share_a_day(window, period) for period in searched):
                reason = (
                    f"scored on a window that overlaps {calibration} "
                    f"(run window {window.start} to {window.end}, {checks.n_samples} samples)"
                )
                return LabelResult("calibrated", active.rule_version, (promoted, reason), ())
            reason = f"{scoring}, outside {calibration}"
            return LabelResult("evaluated", active.rule_version, (promoted, reason), ())
        return LabelResult("calibrated", active.rule_version, (promoted,), ())
    reasons: list[str] = []
    if by is not None:
        reasons.append(f"session {by.session_id} ended {by.session_status}")
    if window is None:
        reasons.append("no score window")
    elif not scored:
        reasons.append(f"{checks.n_samples or 0} samples scored")
    elif by is None:
        reasons.append(f"scored on {window.start} to {window.end}, not promoted by a session")
    return LabelResult("exploratory", active.rule_version, tuple(reasons), ())


__all__ = [
    "CALIBRATED_LABELS",
    "KNOWN_ISSUES_FILENAME",
    "RULE_VERSION",
    "KnownIssue",
    "Label",
    "LabelResult",
    "ValidityRules",
    "known_issues_hitting",
    "label_for",
    "load_known_issues",
    "run_quantities",
]
