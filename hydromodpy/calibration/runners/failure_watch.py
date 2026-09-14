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
"""

from __future__ import annotations

from dataclasses import dataclass, field

from hydromodpy.core.exceptions import CalibrationError

DEFAULT_CONSECUTIVE_FAILURE_LIMIT = 5


class EveryTrialFailedError(CalibrationError):
    """Every trial in a row failed, so the search has nothing to search."""


@dataclass
class ConsecutiveFailureWatch:
    """Raise once ``limit`` trials in a row have failed.

    A ``limit`` of zero disables the watch, for a search that is expected to
    fail its way through a region before finding anything.
    """

    limit: int = DEFAULT_CONSECUTIVE_FAILURE_LIMIT
    _streak: int = field(default=0, init=False)

    def record(self, *, failed: bool, error: str | None) -> None:
        """Note one evaluated trial, and refuse once the streak is reached."""
        if not failed:
            self._streak = 0
            return
        self._streak += 1
        if self.limit and self._streak >= self.limit:
            raise EveryTrialFailedError(
                f"{self._streak} calibration trials in a row failed, the last one with: "
                f"{error or 'no reason recorded'}. The search is stopped rather than "
                "run to its budget on a configuration that cannot be scored."
            )


__all__ = [
    "DEFAULT_CONSECUTIVE_FAILURE_LIMIT",
    "ConsecutiveFailureWatch",
    "EveryTrialFailedError",
]
