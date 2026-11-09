"""What a plan has to say about its cases: errors and warnings, grouped.

An issue of the plan names the cell it comes from (``sites.csv:37 column
x_outlet``), the key it reaches (``geographic.catchment.x_outlet``) and what
is wrong. The same issue on N cases is one line, ``N cases: ...``: a bad
cell of a site row fails every recipe of that site, and a literal value in
the base fails every case.

Each issue is also a ``Diagnostic`` of code ``sites_case``, the one shape every
check of a document gives, so ``hmp.check`` on a ``[sites]`` project and on a
single file answer in the same way.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from hydromodpy.core.diagnostic import Diagnostic, Severity
from hydromodpy.core.exceptions import ConfigError


@dataclass(frozen=True, slots=True)
class PlanIssue:
    """One thing wrong, or worth saying, about one case or about the plan."""

    message: str
    origin: str | None = None
    """The cell or the file the value came from."""

    target: str | None = None
    """The config key the value reaches."""

    case_id: str | None = None
    """The case concerned; None for the plan as a whole."""

    def key(self) -> tuple[str | None, str | None, str]:
        """Return what makes two issues the same issue on two cases."""
        return (self.origin, self.target, self.message)

    def text(self) -> str:
        """Return the issue without its case: origin, target and message."""
        head = " -> ".join(part for part in (self.origin, self.target) if part)
        return f"{head}: {self.message}" if head else self.message

    def diagnostic(self, severity: Severity = "error", *, cases: int = 1) -> Diagnostic:
        """Return the issue as a ``sites_case`` diagnostic, at the key it reaches.

        The case, or the count of the *cases* it touches, leads ``detail``, so the
        text is the line :func:`group_issues` writes. ``path`` is the config key
        of the case document, ``""`` for an issue of the plan as a whole.
        """
        text = self.text()
        if cases > 1:
            detail = f"{cases} cases: {text}"
        elif self.case_id is not None:
            detail = f"{self.case_id}: {text}"
        else:
            detail = text
        return Diagnostic(
            path=self.target or "", code="sites_case", severity=severity, detail=detail
        )


def group_diagnostics(
    issues: Iterable[PlanIssue], severity: Severity = "error"
) -> list[Diagnostic]:
    """Return one diagnostic per distinct issue, counting the cases it touches."""
    groups: OrderedDict[tuple[str | None, str | None, str], list[str | None]] = OrderedDict()
    for issue in issues:
        groups.setdefault(issue.key(), []).append(issue.case_id)
    found: list[Diagnostic] = []
    for (origin, target, message), cases in groups.items():
        named = [case for case in cases if case is not None]
        issue = PlanIssue(
            message=message,
            origin=origin,
            target=target,
            case_id=named[0] if len(named) == 1 else None,
        )
        found.append(issue.diagnostic(severity, cases=len(named)))
    return found


def group_issues(issues: Iterable[PlanIssue]) -> list[str]:
    """Return one line per distinct issue, counting the cases it touches."""
    return [diagnostic.detail for diagnostic in group_diagnostics(issues)]


class PlanError(ConfigError):
    """The plan cannot be written: its issues, one line each."""

    def __init__(self, issues: Sequence[PlanIssue]) -> None:
        lines = group_issues(issues)
        super().__init__("\n".join(lines))
        self.lines = tuple(lines)


__all__ = ["PlanError", "PlanIssue", "group_diagnostics", "group_issues"]
