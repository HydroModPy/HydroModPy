"""Stop a search whose trials all fail instead of letting it finish empty.

A trial that raises while its objective is extracted is caught, scored as a
failure and logged. That is right for one bad candidate in an otherwise healthy
search. It is wrong for a mis-configured calibration, where every trial fails the
same way: the session then runs its whole budget, logs one warning per trial
among the solver's own output, completes, and reports a best candidate chosen
between values that all came from the same error.

The watch turns that into a single refusal naming the reason. It counts
consecutive failures rather than a ratio, because the case worth catching is
systematic and shows up immediately, while a ratio would only fire once most of
the budget had already been spent.

A trial whose candidate puts a parameter the search moves outside its physical
range is infeasible. Its error text starts with :data:`INFEASIBLE_PREFIX`, the
optimizer gets the failed cost, and the streak leaves it out: the refusal says
something about that point, not about the configuration, so it neither counts
nor clears the streak. A search that has scored no point at all after
``infeasible_limit`` infeasible trials is refused all the same, because then no
point of its bounds can be modeled and the budget would be spent at the failed
cost. Once one point is scored, an infeasible region is a region the search can
walk out of, and a grid or a sample may cross many of them in a row.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from hydromodpy.core.exceptions import CalibrationError

DEFAULT_CONSECUTIVE_FAILURE_LIMIT = 5

# Five generations of a CMA-ES population of ten, or fifty samples of which not
# one fell where the model can run.
DEFAULT_INFEASIBLE_LIMIT = 50

INFEASIBLE_PREFIX = "infeasible"
"""How the error text of a trial out of physical bounds starts."""


class EveryTrialFailedError(CalibrationError):
    """Every trial in a row failed, so the search has nothing to search."""


@dataclass
class ConsecutiveFailureWatch:
    """Raise once ``limit`` trials in a row have failed.

    Raise too once ``infeasible_limit`` trials were infeasible while none has
    been scored yet. A limit of zero disables its check, for a search that is
    expected to fail its way through a region before finding anything.
    """

    limit: int = DEFAULT_CONSECUTIVE_FAILURE_LIMIT
    infeasible_limit: int = DEFAULT_INFEASIBLE_LIMIT
    _streak: int = field(default=0, init=False)
    _infeasible: int = field(default=0, init=False)
    _scored: bool = field(default=False, init=False)

    def record(self, *, failed: bool, error: str | None) -> None:
        """Note one evaluated trial, and refuse once a limit is reached."""
        if not failed:
            self._streak = 0
            self._scored = True
            return
        if (error or "").startswith(INFEASIBLE_PREFIX):
            self._record_infeasible(error)
            return
        self._streak += 1
        if self.limit and self._streak >= self.limit:
            raise EveryTrialFailedError(
                f"{self._streak} calibration trials in a row failed, the last one with: "
                f"{error or 'no reason recorded'}. The search is stopped rather than "
                "run to its budget on a configuration that cannot be scored."
            )

    def _record_infeasible(self, error: str | None) -> None:
        if self._scored:
            return
        self._infeasible += 1
        if self.infeasible_limit and self._infeasible >= self.infeasible_limit:
            raise EveryTrialFailedError(
                f"{self._infeasible} calibration trials were infeasible and none has been "
                f"scored yet, the last one with: {error}. The bounds the search walks "
                "between, or the values they scale, leave the physical range of a "
                "parameter at every point tried: narrow them."
            )


__all__ = [
    "DEFAULT_CONSECUTIVE_FAILURE_LIMIT",
    "DEFAULT_INFEASIBLE_LIMIT",
    "ConsecutiveFailureWatch",
    "EveryTrialFailedError",
    "INFEASIBLE_PREFIX",
]
