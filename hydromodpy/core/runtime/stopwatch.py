"""The one stopwatch of a run: how long a step, a solve, a figure or an export took.

``measured`` times a block with ``perf_counter`` and reads the high-water mark
of the process memory when the block ends, an exception included, so a step
that fails still has its line. The memory is the peak of the whole process at
that moment, not the peak of the block alone: a per-block peak would need
``tracemalloc``, which costs more than most steps it would measure. It is
``None`` where the ``resource`` module is absent (Windows).

``process_age_s`` says how long the process has lived, which tells the start-up
cost of a command apart from the time of its steps.
"""

from __future__ import annotations

import os
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime

MEASURE_KINDS: tuple[str, ...] = ("step", "solve", "figure", "export")
"""What a measure times: a pipeline step, one solve, one figure or one export."""


@dataclass(slots=True)
class Measure:
    """The time and memory of one block.

    ``started_at`` is the UTC instant the block began. ``duration_s`` is its
    wall time in seconds, set when the block ends. ``max_rss_mb`` is the peak
    resident memory of the process in MiB at that moment, or ``None`` when the
    platform does not say.
    """

    kind: str
    name: str
    started_at: datetime
    duration_s: float | None = None
    max_rss_mb: float | None = None

    def __post_init__(self) -> None:
        if self.kind not in MEASURE_KINDS:
            raise ValueError(
                f"A measure kind is one of {', '.join(MEASURE_KINDS)}; got {self.kind!r}."
            )


def max_rss_mb() -> float | None:
    """The peak resident memory of this process in MiB, or ``None`` without ``resource``.

    ``ru_maxrss`` counts KiB on Linux and bytes on macOS.
    """
    try:
        import resource
    except ImportError:
        return None
    peak = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    if sys.platform == "darwin":
        return peak / (1024.0 * 1024.0)
    return peak / 1024.0


@contextmanager
def measured(kind: str, name: str) -> Iterator[Measure]:
    """Time the block and fill the ``Measure`` it yields when the block ends."""
    measure = Measure(kind=kind, name=name, started_at=datetime.now(UTC))
    start = time.perf_counter()
    try:
        yield measure
    finally:
        measure.duration_s = time.perf_counter() - start
        measure.max_rss_mb = max_rss_mb()


def _boot_time_s() -> float | None:
    """The boot instant of a Linux host in seconds since the epoch, from ``/proc/stat``."""
    try:
        with open("/proc/stat", encoding="ascii") as handle:
            for line in handle:
                if line.startswith("btime "):
                    return float(line.split()[1])
    except OSError:
        return None
    return None


def process_age_s() -> float | None:
    """How long this process has lived, in seconds, or ``None`` where it cannot be read.

    Linux reads ``/proc/self/stat``, whose field 22 is the start time in clock
    ticks after boot. Elsewhere ``psutil`` answers when it is installed.
    """
    try:
        with open("/proc/self/stat", encoding="ascii") as handle:
            stat = handle.read()
    except OSError:
        stat = None
    if stat is not None:
        boot = _boot_time_s()
        if boot is not None:
            # The command name in field 2 may hold spaces, so split after its parenthesis.
            fields = stat.rsplit(")", 1)[1].split()
            ticks = float(fields[19])
            started = boot + ticks / float(os.sysconf("SC_CLK_TCK"))
            return max(time.time() - started, 0.0)
    try:
        import psutil
    except ImportError:
        return None
    return max(time.time() - float(psutil.Process().create_time()), 0.0)


__all__ = ["MEASURE_KINDS", "Measure", "max_rss_mb", "measured", "process_age_s"]
