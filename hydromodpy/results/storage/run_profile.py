"""``profile.json``: where a run spent its time and memory, attempt by attempt.

The pipeline measures each step with ``core.runtime.stopwatch.measured`` and
rewrites the profile after each step, so a stopped run still says what it did.
A resume adds its lines under its own attempt number; a step rebuilt from the
checkpoints of an earlier attempt is marked ``reused = "prefix"``, and a
product read from the project store ``reused = "store"`` with its store key.
The ``run_solver`` step writes one ``solve`` line per run of the plan, the time
of the solve alone, and the display and export steps one line per figure and
per export.

The document is outside the seal and the identity: it describes one machine,
not what the run computed. It is rewritten through a temporary file and one
rename, about 0.2 ms for forty lines, so a process killed while it writes
leaves the previous document whole.

A pipeline without a run directory, a calibration trial, writes no document.
Its lines go to the collector :func:`collected_profile` opened in the same
context, and the session writes them in the journal line of the trial.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any

from hydromodpy.core.runtime.stopwatch import MEASURE_KINDS, Measure
from hydromodpy.results.storage.contract import RUN_PROFILE_FILENAME
from hydromodpy.results.storage.json_io import read_transient_json, write_json_atomic

PROFILE_SCHEMA = "hydromodpy.profile.v1"
"""Schema of ``profile.json``."""

REUSED_KINDS: tuple[str, ...] = ("no", "prefix", "store", "sealed", "rerun")
"""Whether a line was computed (``no``), rebuilt from an earlier attempt
(``prefix``), read from the project store (``store``), read from the
``mesh/`` sealed beside the source of a replay (``sealed``), or solved by
rerunning the run of the previous calibration trial with new properties
(``rerun``, written only on the solve line of a trial)."""


@dataclass(frozen=True, slots=True)
class ProfileLine:
    """One measured block of one attempt.

    ``kind`` is ``step``, ``solve``, ``figure`` or ``export``. ``started_at``
    is a UTC instant, ``duration_s`` the wall time in seconds and
    ``max_rss_mb`` the peak memory of the process in MiB when the block ended,
    ``None`` where the platform does not say. ``reused`` is one of
    :data:`REUSED_KINDS`, and ``key`` the store key of a ``store`` line,
    ``None`` on any other line.
    """

    kind: str
    name: str
    attempt: int
    started_at: datetime
    duration_s: float | None
    max_rss_mb: float | None = None
    reused: str = "no"
    key: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in MEASURE_KINDS:
            raise ValueError(
                f"A profile line kind is one of {', '.join(MEASURE_KINDS)}; got {self.kind!r}."
            )
        if self.reused not in REUSED_KINDS:
            raise ValueError(
                f"A profile line is reused as one of {', '.join(REUSED_KINDS)}; "
                f"got {self.reused!r}."
            )
        if (self.reused == "store") != (self.key is not None):
            raise ValueError(
                "A profile line carries a store key exactly when it was read from the "
                f"store; got reused = {self.reused!r} and key = {self.key!r}."
            )
        if int(self.attempt) < 1:
            raise ValueError(f"A profile line attempt counts from 1; got {self.attempt!r}.")

    @classmethod
    def of(
        cls, measure: Measure, *, attempt: int, reused: str = "no", key: str | None = None
    ) -> ProfileLine:
        """The line of a finished ``measure`` in ``attempt``."""
        return cls(
            kind=measure.kind,
            name=measure.name,
            attempt=attempt,
            started_at=measure.started_at,
            duration_s=measure.duration_s,
            max_rss_mb=measure.max_rss_mb,
            reused=reused,
            key=key,
        )

    def to_dict(self) -> dict[str, Any]:
        """The JSON object of this line."""
        return {
            "kind": self.kind,
            "name": self.name,
            "attempt": int(self.attempt),
            "started_at": self.started_at.isoformat(),
            "duration_s": self.duration_s,
            "max_rss_mb": self.max_rss_mb,
            "reused": self.reused,
            "key": self.key,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> ProfileLine:
        """The line a JSON object of ``profile.json`` holds."""
        return cls(
            kind=str(payload["kind"]),
            name=str(payload["name"]),
            attempt=int(payload["attempt"]),
            started_at=datetime.fromisoformat(str(payload["started_at"])),
            duration_s=_optional_float(payload.get("duration_s")),
            max_rss_mb=_optional_float(payload.get("max_rss_mb")),
            reused=str(payload.get("reused", "no")),
            key=None if payload.get("key") is None else str(payload["key"]),
        )


def _optional_float(value: Any) -> float | None:
    return None if value is None else float(value)


@dataclass(frozen=True, slots=True)
class Profile:
    """The lines of every attempt of one run, in the order they were measured.

    ``process_age_s`` maps an attempt to the age of its process in seconds
    when the pipeline began, which is the start-up cost of the command, or
    ``None`` where it cannot be read.
    """

    lines: tuple[ProfileLine, ...] = ()
    process_age_s: Mapping[int, float | None] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(self, "lines", tuple(self.lines))
        object.__setattr__(
            self,
            "process_age_s",
            MappingProxyType(
                {int(k): _optional_float(v) for k, v in dict(self.process_age_s).items()}
            ),
        )

    def with_start(self, attempt: int, process_age_s: float | None) -> Profile:
        """This profile with the start-up of ``attempt``."""
        ages = {**self.process_age_s, int(attempt): process_age_s}
        return replace(self, process_age_s=ages)

    def with_line(self, line: ProfileLine) -> Profile:
        """This profile with ``line`` added at the end."""
        return replace(self, lines=(*self.lines, line))

    def of_attempt(self, attempt: int) -> tuple[ProfileLine, ...]:
        """The lines of one attempt, in order."""
        return tuple(line for line in self.lines if line.attempt == int(attempt))

    def to_dict(self) -> dict[str, Any]:
        """The JSON document of ``profile.json``."""
        return {
            "schema": PROFILE_SCHEMA,
            "process_age_s": {str(k): v for k, v in sorted(self.process_age_s.items())},
            "lines": [line.to_dict() for line in self.lines],
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> Profile:
        """The profile a ``profile.json`` document holds."""
        return cls(
            lines=tuple(ProfileLine.from_dict(line) for line in payload.get("lines", ())),
            process_age_s={int(k): v for k, v in dict(payload.get("process_age_s") or {}).items()},
        )


def profile_path(run_dir: Path) -> Path:
    """Return ``<run>/profile.json``."""
    return Path(run_dir) / RUN_PROFILE_FILENAME


def write_profile(run_dir: Path, profile: Profile) -> Path:
    """Write ``profile`` to ``<run>/profile.json`` through one rename, and return the path."""
    return write_json_atomic(profile_path(run_dir), profile.to_dict())


def read_profile(run_dir: Path) -> Profile | None:
    """Return the profile of the run at ``run_dir``, or ``None`` when it has none.

    A run of HydroModPy 2.0 has no ``profile.json``. A document of another
    schema is refused with :class:`~hydromodpy.core.exceptions.SchemaVersionMismatchError`.
    """
    path = profile_path(run_dir)
    if not path.is_file():
        return None
    return Profile.from_dict(read_transient_json(path, PROFILE_SCHEMA))


_COLLECTED: ContextVar[list[ProfileLine] | None] = ContextVar("collected_profile", default=None)
"""Lines of a pipeline without a run directory, in the context that opened a collector.

A context variable belongs to its context, so two trials played in two threads
never mix their lines.
"""


@contextmanager
def collected_profile() -> Iterator[list[ProfileLine]]:
    """Collect, in this context, the profile lines of a pipeline that has no run directory.

    The yielded list fills as the blocks end. A collector opened inside another
    one hides it until it closes.
    """
    lines: list[ProfileLine] = []
    token = _COLLECTED.set(lines)
    try:
        yield lines
    finally:
        _COLLECTED.reset(token)


def collect_line(line: ProfileLine) -> bool:
    """Add ``line`` to the collector open in this context; return whether one was open."""
    collector = _COLLECTED.get()
    if collector is None:
        return False
    collector.append(line)
    return True


__all__ = [
    "PROFILE_SCHEMA",
    "REUSED_KINDS",
    "Profile",
    "ProfileLine",
    "collect_line",
    "collected_profile",
    "profile_path",
    "read_profile",
    "write_profile",
]
