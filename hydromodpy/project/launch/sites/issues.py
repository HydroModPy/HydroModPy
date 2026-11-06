"""What a plan has to say about its cases: errors and warnings, grouped.

An issue of the plan names the cell it comes from (``sites.csv:37 column
x_outlet``), the key it reaches (``geographic.catchment.x_outlet``) and what
is wrong. The same issue on N cases is one line, ``N cases: ...``: a bad
cell of a site row fails every recipe of that site, and a literal value in
the base fails every case.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

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


def group_issues(issues: Iterable[PlanIssue]) -> list[str]:
    """Return one line per distinct issue, counting the cases it touches."""
    groups: OrderedDict[tuple[str | None, str | None, str], list[str | None]] = OrderedDict()
    for issue in issues:
        groups.setdefault(issue.key(), []).append(issue.case_id)
    lines: list[str] = []
    for (origin, target, message), cases in groups.items():
        text = PlanIssue(message=message, origin=origin, target=target).text()
        named = [case for case in cases if case is not None]
        if len(named) > 1:
            lines.append(f"{len(named)} cases: {text}")
        elif len(named) == 1:
            lines.append(f"{named[0]}: {text}")
        else:
            lines.append(text)
    return lines


class PlanError(ConfigError):
    """The plan cannot be written: its issues, one line each."""

    def __init__(self, issues: Sequence[PlanIssue]) -> None:
        lines = group_issues(issues)
        super().__init__("\n".join(lines))
        self.lines = tuple(lines)


__all__ = ["PlanError", "PlanIssue", "group_issues"]
