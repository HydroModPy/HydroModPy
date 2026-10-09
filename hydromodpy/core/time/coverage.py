"""Which samples of a forcing record a stress period takes, and when it is covered.

One rule for every forcing record: a series, a station or a grid with a time
axis.

1. A period ``[b_i, b_{i+1})`` takes the samples stamped inside it, with equal
   weights.
2. A sample is the rate of the interval from its stamp to the next stamp. The
   last sample stands for one step of the record: the median spacing of its
   stamps. A record of one sample stands for all later time.
3. A period with no sample inside is covered when the interval of the latest
   earlier sample reaches into it. It takes that sample.
4. A period that no interval reaches is not covered: it lies before the first
   stamp, or after the end of the last step. ``simulation.time.coverage_policy``
   decides: ``"error"`` stops the run, ``"warn"`` warns once per record,
   ``"ignore"`` says nothing. Under the last two, the period takes the nearest
   sample in time: the last one after the record, the first one before it.

The rule never looks at the values, only at the stamps.
"""

from __future__ import annotations

import warnings
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import pandas as pd

COVERAGE_POLICIES: tuple[str, ...] = ("error", "warn", "ignore")


@dataclass(frozen=True)
class PeriodSamples:
    """The samples each period takes, by position in the sorted stamps.

    ``inside[i]`` lists the samples stamped in period ``i``. ``fill[i]`` is the
    sample a period with none inside takes, or -1 when it has samples inside.
    ``uncovered`` lists the periods no sample interval reaches.
    """

    inside: tuple[np.ndarray, ...]
    fill: np.ndarray
    uncovered: tuple[int, ...]


def record_step(stamps: pd.DatetimeIndex) -> pd.Timedelta | None:
    """Return the step of a record, the median spacing of its stamps.

    None for a record of one sample, which stands for all later time.
    """
    if len(stamps) < 2:
        return None
    spacing = np.diff(pd.DatetimeIndex(stamps).as_unit("ns").asi8)
    return pd.Timedelta(int(np.median(spacing)), unit="ns")


def samples_by_period(
    stamps: Sequence[object] | pd.DatetimeIndex,
    boundaries: Sequence[object],
) -> PeriodSamples:
    """Match the stamps of one record to the periods of ``boundaries``.

    ``stamps`` must be sorted. ``boundaries`` holds the ``N + 1`` period edges.
    """
    # One unit for stamps and edges: a parquet or DuckDB index often comes in
    # microseconds, and its integers would not compare with nanosecond edges.
    index = pd.DatetimeIndex(stamps).as_unit("ns")
    if len(index) == 0:
        raise ValueError("a forcing record needs at least one sample.")
    if not index.is_monotonic_increasing:
        raise ValueError("the stamps of a forcing record must be sorted.")
    edges = pd.DatetimeIndex(boundaries).as_unit("ns")
    step = record_step(index)
    record_end = None if step is None else index[-1] + step

    inside: list[np.ndarray] = []
    fill = np.full(max(len(edges) - 1, 0), -1, dtype=int)
    uncovered: list[int] = []
    values = index.asi8
    edge_values = edges.asi8
    for i, (left, right) in enumerate(zip(edge_values[:-1], edge_values[1:], strict=False)):
        first = int(np.searchsorted(values, left, side="left"))
        stop = int(np.searchsorted(values, right, side="left"))
        inside.append(np.arange(first, stop, dtype=int))
        if stop > first:
            continue
        if first == 0:
            # Before the first stamp: nothing is in force yet.
            fill[i] = 0
            uncovered.append(i)
            continue
        fill[i] = first - 1
        if record_end is not None and first == len(index) and record_end <= edges[i]:
            uncovered.append(i)
    return PeriodSamples(inside=tuple(inside), fill=fill, uncovered=tuple(uncovered))


def enforce_coverage(
    periods: PeriodSamples,
    boundaries: Sequence[object],
    *,
    policy: str,
    label: str,
) -> None:
    """Apply ``coverage_policy`` to the periods a record does not cover."""
    if policy not in COVERAGE_POLICIES:
        raise ValueError(
            f"simulation.time.coverage_policy must be one of {list(COVERAGE_POLICIES)}, "
            f"got {policy!r}."
        )
    if not periods.uncovered or policy == "ignore":
        return
    edges = pd.DatetimeIndex(boundaries)
    shown = ", ".join(
        f"{i} [{edges[i].date()}, {edges[i + 1].date()})" for i in periods.uncovered[:5]
    )
    more = len(periods.uncovered) - 5
    if more > 0:
        shown += f" and {more} more"
    message = (
        f"{label} does not cover stress period(s) {shown}: no sample of the record is "
        "in force there."
    )
    if policy == "error":
        raise ValueError(
            message + " Extend the record, shorten [simulation.time], or set "
            "simulation.time.coverage_policy to 'warn' or 'ignore' to fill these "
            "periods with the nearest sample."
        )
    warnings.warn(
        message + " They take the nearest sample (coverage_policy = 'warn').",
        UserWarning,
        stacklevel=3,
    )


__all__ = [
    "COVERAGE_POLICIES",
    "PeriodSamples",
    "enforce_coverage",
    "record_step",
    "samples_by_period",
]
