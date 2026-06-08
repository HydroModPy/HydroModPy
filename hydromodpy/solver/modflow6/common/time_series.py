"""Package-agnostic MF6 TS6 (external time-series) attachment helpers.

Every MF6 boundary package that owns time-series fields exposes a ``.ts`` child
package (LAK, WEL, MAW, SFR, GHB, DRN, EVT, RCH, ...). This module turns a small
immutable series spec into the FloPy ``timeseries`` payload and attaches it to an
already-built package through that ``.ts`` protocol. It imports nothing
package-specific so any builder can reuse it: emit a series NAME string into a
stress-period row and accumulate a :class:`Ts6Series`, then call
:func:`attach_time_series` right after the package is constructed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from hydromodpy.core.exceptions import SolverInputError

if TYPE_CHECKING:
    from collections.abc import Sequence

# MF6 holds a name in a 16-character identifier field; longer names are truncated
# at write time, which silently aliases two series. We reject those up front.
_MAX_TS6_NAME_LEN = 16

Ts6Interpolation = Literal["stepwise", "linear", "linearend"]


@dataclass(frozen=True)
class Ts6Series:
    """One named external time series for an MF6 TS6 file.

    ``times`` are simulation-relative TDIS times (seconds for an HMP run) and must
    be strictly increasing. ``interpolation`` defaults to ``stepwise``, which holds
    each value constant from its time up to the next, reproducing a per-period
    constant forcing exactly.
    """

    name: str
    times: tuple[float, ...]
    values: tuple[float, ...]
    interpolation: Ts6Interpolation = "stepwise"
    sfac: float | None = None


def build_ts6_table(
    series: Sequence[Ts6Series],
) -> tuple[list[list[float]], list[str], list[str]]:
    """Pack series that share one time axis into FloPy TS6 records.

    Returns ``(timeseries, time_series_namerecord, interpolation_methodrecord)``
    where ``timeseries`` is the recarray rows ``[[t, v0, v1, ...], ...]`` with one
    value column per series. Raises when the series do not share the same strictly
    increasing ``times`` or when names collide; the caller then splits the
    mismatched series into separate files via ``append_package``.
    """
    if not series:
        raise SolverInputError("build_ts6_table requires at least one series.")

    names = [s.name for s in series]
    if len(set(names)) != len(names):
        raise SolverInputError(f"TS6 series names must be unique; got {names}.")
    for name in names:
        if not name:
            raise SolverInputError("TS6 series name must be non-empty.")
        if len(name) > _MAX_TS6_NAME_LEN:
            raise SolverInputError(
                f"TS6 series name '{name}' exceeds the MF6 {_MAX_TS6_NAME_LEN}-char limit."
            )

    reference = series[0].times
    _validate_times(reference)
    for s in series:
        if s.times != reference:
            raise SolverInputError(
                "All TS6 series in one file must share the same time axis; "
                f"'{s.name}' differs from '{series[0].name}'."
            )
        if len(s.values) != len(reference):
            raise SolverInputError(
                f"TS6 series '{s.name}' has {len(s.values)} values for {len(reference)} times."
            )

    timeseries = [
        [float(reference[i]), *(float(s.values[i]) for s in series)] for i in range(len(reference))
    ]
    namerecord = [s.name for s in series]
    methodrecord = [str(s.interpolation) for s in series]
    return timeseries, namerecord, methodrecord


def attach_time_series(
    package: object,
    series: Sequence[Ts6Series],
    *,
    filename: str,
) -> None:
    """Attach a TS6 file of named series to an already-built MF6 package.

    Operates on any FloPy MF6 package owning a ``.ts`` child container. The first
    file initializes the container; later calls append additional files so several
    time axes can coexist on one package.
    """
    timeseries, namerecord, methodrecord = build_ts6_table(series)
    ts = getattr(package, "ts", None)
    if ts is None:
        raise SolverInputError(
            f"{type(package).__name__} has no '.ts' child package; it does not "
            "support TS6 time series."
        )
    sfacrecord = _resolve_sfacrecord(series)
    attached = bool(getattr(package, "_hmp_ts_attached", False))
    initialize = ts.append_package if attached else ts.initialize
    initialize(
        time_series_namerecord=namerecord,
        interpolation_methodrecord=methodrecord,
        sfacrecord=sfacrecord,
        timeseries=timeseries,
        filename=filename,
    )
    setattr(package, "_hmp_ts_attached", True)  # noqa: B010


def _resolve_sfacrecord(series: Sequence[Ts6Series]) -> list[list[float]] | None:
    """Return the FloPy ``sfacrecord`` when any series declares a scale factor."""
    if all(s.sfac is None for s in series):
        return None
    return [[float(s.sfac) if s.sfac is not None else 1.0] for s in series]


def _validate_times(times: tuple[float, ...]) -> None:
    """Reject an empty or non-strictly-increasing TS6 time axis."""
    if not times:
        raise SolverInputError("TS6 series must declare at least one time.")
    for earlier, later in zip(times, times[1:], strict=False):
        if later <= earlier:
            raise SolverInputError(
                f"TS6 times must be strictly increasing; got {earlier} then {later}."
            )


__all__ = [
    "Ts6Interpolation",
    "Ts6Series",
    "attach_time_series",
    "build_ts6_table",
]
