"""Repeating a whole search to say how far apart its answers land.

``cost_profile`` reads one search's own trace: it says what that search could not
tell apart, which is a statement about the trace and not about the problem. It
cannot see a second basin, because a single descent never visited one. Restarting
the search from elsewhere can.

The constraint this obeys is the project's: a calibration always reports one
manipulable value, and an interval sits beside it, never in its place. So the best
restart IS the answer, unchanged in kind from a single search, and the spread of
the others is reported next to it. A reader who wants the number gets the number.

What it costs is stated rather than hidden: each restart is a full search, so eight
restarts of a hundred-evaluation phase is eight hundred model runs.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any

import numpy as np

from hydromodpy.calibration.optim.optimizer import engine_traits
from hydromodpy.calibration.optim.parameters import ParameterSpace
from hydromodpy.calibration.optim.sampling import search_space_samples
from hydromodpy.calibration.optim.stopping import settled

if TYPE_CHECKING:
    from hydromodpy.calibration.report import CalibrationReport


@dataclass(frozen=True)
class RestartSpread:
    """What the restarts of one search disagreed about."""

    parameter: str
    best: float
    lowest: float
    highest: float
    values: tuple[float, ...] = field(default_factory=tuple)

    @property
    def spans_a_decade(self) -> bool:
        """Whether the restarts landed more than a factor ten apart.

        Not a verdict, a flag a reader needs: a parameter whose optima span a
        decade was not identified by this calibration, however tight the cost
        profile of any one restart looked.
        """
        if self.lowest <= 0.0 or self.highest <= 0.0:
            return abs(self.highest - self.lowest) > 0.0 and self.lowest != self.highest
        return (self.highest / self.lowest) > 10.0

    def to_dict(self) -> dict[str, object]:
        return {
            "parameter": self.parameter,
            "best": self.best,
            "lowest": self.lowest,
            "highest": self.highest,
            "n_restarts": len(self.values),
            "spans_a_decade": self.spans_a_decade,
        }


def assert_restarts_can_explore(method: str, restarts: int) -> None:
    """Refuse restarts on an engine that would return the same answer every time.

    Reporting the spread of identical runs as an uncertainty states a certainty the
    search never established. An exhaustive sweep and a root search are the two
    that declare it.
    """
    if restarts < 2:
        raise ValueError(
            f"[calibration.uncertainty] restarts={restarts} repeats nothing; a spread "
            "needs at least two searches."
        )
    if not engine_traits(method).restarts_explore_differently:
        raise ValueError(
            f"[calibration.uncertainty] method='multistart' repeats the search, and "
            f"{method!r} returns the same answer every time: it visits the same points in "
            "the same order whatever the seed. Reporting the spread of identical runs as "
            "an uncertainty would state a certainty nothing established. Use "
            "method='cost_profile', or run this phase on an engine a restart can move."
        )


def start_points(space: ParameterSpace, *, restarts: int, seed: int | None) -> list[np.ndarray]:
    """Return one start per restart, drawn from the declared sampling of each parameter.

    The first is left to the engine, which is what makes restart one identical to
    the single search it replaces: the answer a file already published stays in the
    set, and the others are added around it.
    """
    rng = np.random.default_rng(seed)
    drawn = search_space_samples(space, rng, max(0, restarts - 1))
    return [None, *[np.asarray(row, dtype=float) for row in drawn]]


def run_side_by_side(
    function: Callable[[Any], Any],
    items: Iterable[Any],
    *,
    width: int,
    on_stop: Callable[[], None] | None = None,
) -> list[Any]:
    """Return ``function(item)`` for each item, ``width`` at a time, in the order of the items.

    The threads only wait on the workers of a pool. A failure, or an interrupt of
    the caller, calls ``on_stop`` and starts no item that is still queued, so
    nothing waits on a solve no one will read.
    """
    with ThreadPoolExecutor(width) as pool:
        futures = [pool.submit(function, item) for item in items]
        try:
            for future in as_completed(futures):
                future.result()
        except BaseException:
            pool.shutdown(wait=False, cancel_futures=True)
            if on_stop is not None:
                on_stop()
            raise
    return [future.result() for future in futures]


def run_restarts(
    run_one: Callable[[int, np.ndarray | None, int], object],
    *,
    method: str,
    space: ParameterSpace,
    restarts: int,
    seed: int | None,
    width: int = 1,
    on_stop: Callable[[], None] | None = None,
) -> tuple[object, tuple[RestartSpread, ...]]:
    """Run the search ``restarts`` times and return the best report and the spread.

    ``run_one(seed, start_at, index)`` performs one whole search. At a ``width``
    above one the restarts run side by side, ``width`` at a time, and ``on_stop``
    is called when one fails or the caller is interrupted. A restart that returns
    no best parameters is kept out of the spread rather than counted as a zero: a
    search that failed did not find a different optimum, it found none. The answer
    is the lowest cost among the restarts that settled, or among all of them when
    none did. When a restart found nothing, the others stand and the phase closes
    ``partial``.
    """
    assert_restarts_can_explore(method, restarts)
    base = 0 if seed is None else int(seed)
    starts = start_points(space, restarts=restarts, seed=seed)
    runs = [(base + index, start, index) for index, start in enumerate(starts)]
    if width <= 1:
        reports = [run_one(*run) for run in runs]
    else:
        reports = run_side_by_side(
            lambda run: run_one(*run), runs, width=min(width, restarts), on_stop=on_stop
        )
    scored = [r for r in reports if r is not None and _objective_of(r) is not None]
    if not scored:
        return reports[0], ()
    best = min([r for r in scored if unsettled_search(r) is None] or scored, key=_objective_of)
    if len(scored) < len(reports) and best.extra.get("search_status") == "completed":
        best = replace(best, status="partial", extra={**best.extra, "search_status": "partial"})
    return best, spread_of(scored, best=best, names=list(space.names))


def spread_of(reports: list, *, best: object, names: list[str]) -> tuple[RestartSpread, ...]:
    """Return, per parameter, what the restarts that scored actually landed on."""
    out: list[RestartSpread] = []
    for name in names:
        values = [
            float(getattr(r, "best_parameters", None)[name])
            for r in reports
            if getattr(r, "best_parameters", None) and name in r.best_parameters
        ]
        if not values:
            continue
        chosen = getattr(best, "best_parameters", None) or {}
        out.append(
            RestartSpread(
                parameter=name,
                best=float(chosen.get(name, values[0])),
                lowest=min(values),
                highest=max(values),
                values=tuple(values),
            )
        )
    return tuple(out)


def unsettled_search(report: CalibrationReport) -> Mapping[str, Any] | None:
    """Return the report's search record when it says the search did not settle, else None.

    The record is ``extra["search"]``, written by the runner that solved the
    phase. A report without one (a phase reused from disk) is judged on its
    best candidate alone.
    """
    search = report.extra.get("search")
    if isinstance(search, Mapping) and not settled(search["stop_state"], search["stopping_rule"]):
        return search
    return None


def _objective_of(report: object) -> float | None:
    value = getattr(report, "best_cost", None)
    if value is None:
        return None
    number = float(value)
    return None if number != number else number


__all__ = [
    "RestartSpread",
    "assert_restarts_can_explore",
    "run_restarts",
    "run_side_by_side",
    "spread_of",
    "start_points",
    "unsettled_search",
]
