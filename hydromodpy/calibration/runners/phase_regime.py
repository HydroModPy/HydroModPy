"""What a phase's flow regime writes into the model its trials run.

A phase says ``regime = "steady"`` or ``regime = "transient"``, and this module
turns it into the dotted-path overrides ``prepare_trials`` writes before the
prepared prefix runs. It is the one place that translation lives: a phase
written by hand and a phase a protocol writes go through it alike.

Steady is one period over a window: the phase's ``steady_window`` when it gives
one, otherwise the extent of ``[simulation.time]``. The recharge over that
period averages to its mean, and a steady solve carries no storage. Transient
is the project's own time grid: only the regime is restated.

The window is read from the raw configuration document, not from the loaded
model: calibration does not import the ``config`` layer.
``config.PHASE_REGIME_PATHS`` lists the paths each regime writes, so a phase
that writes one of them in ``overrides`` too is refused when the file is read.
"""

from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import Any

import pandas as pd

from hydromodpy.calibration.config import CalibPhaseDecl


def phase_overrides(phase: CalibPhaseDecl, document: Mapping[str, Any]) -> dict[str, Any]:
    """Return every dotted path a phase's trials run with: its regime's, then its own.

    ``document`` is the raw configuration the phase belongs to, ``base_config``
    merged, where ``[simulation.time]`` is read. A phase that gives no regime
    returns its own ``overrides`` unchanged.
    """
    return {**regime_overrides(phase, document), **phase.overrides}


def regime_overrides(phase: CalibPhaseDecl, document: Mapping[str, Any]) -> dict[str, Any]:
    """Return the dotted paths a phase's ``regime`` writes, empty when it gives none."""
    if phase.regime is None:
        return {}
    if phase.regime == "transient":
        return {"flow.flow_regime": "transient"}
    steady_start, steady_end = _steady_window(phase.steady_window, document)
    start, end = pd.Timestamp(steady_start), pd.Timestamp(steady_end)
    if (start.tzinfo is None) != (end.tzinfo is None):
        raise ValueError(
            f"the steady stage spans {steady_start} to {steady_end}, where one bound "
            "carries a UTC offset and the other does not, so the span is undefined. "
            "Write both with an offset, or neither."
        )
    span_days = (end - start).days + 1
    if span_days < 1:
        raise ValueError(
            f"the steady stage spans {steady_start} to {steady_end}, which is not a forward window."
        )
    return {
        "flow.flow_regime": "steady",
        "simulation.time.start_datetime": steady_start,
        "simulation.time.end_datetime": steady_end,
        "simulation.time.step_unit": "day",
        "simulation.time.step_value": span_days,
    }


def _canonical_instant(value: Any, source: str) -> str:
    """Return the one spelling of an instant a TOML file can write three ways.

    ``start_datetime = 2000-01-01`` parses as a date, ``2000-01-01T00:00:00`` as
    a datetime, and a quoted value stays a string. The overrides a steady phase
    writes must not depend on which spelling a file chose: a run re-read from
    its own sealed config runs the model it ran, not one that differs by a
    rendered midnight.

    The spelling is a function of the instant alone. A naive bound that falls on
    midnight is written as its date, because a steady window is read in days and
    that is the half of the span that carries information. A bound carrying an
    offset keeps its offset: dropping it would move the instant by that much,
    silently, and two offsets apart would collapse onto the same date.

    Only a date, a datetime or a string is read. A bare number is not a
    misspelling of an instant, it is a different kind of value, and pandas would
    take it for nanoseconds since the epoch.
    """
    if not isinstance(value, (str, datetime.date, datetime.datetime, pd.Timestamp)):
        raise ValueError(f"{source} is not an instant a steady phase can read: {value!r}.")
    try:
        stamp = pd.Timestamp(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{source} is not an instant a steady phase can read: {value!r}.") from exc
    if stamp is pd.NaT:
        raise ValueError(f"{source} is not an instant a steady phase can read: {value!r}.")
    if stamp.tzinfo is None and stamp == stamp.normalize():
        return stamp.strftime("%Y-%m-%d")
    return stamp.isoformat()


def _steady_window(
    window: Mapping[str, Any] | None, document: Mapping[str, Any]
) -> tuple[str, str]:
    if window is not None:
        missing = [key for key in ("start", "end") if not window.get(key)]
        if missing:
            raise ValueError(
                f"steady_window needs both 'start' and 'end'; missing {', '.join(missing)}."
            )
        source = "steady_window"
        return (
            _canonical_instant(window["start"], f"{source}.start"),
            _canonical_instant(window["end"], f"{source}.end"),
        )

    time = (document.get("simulation") or {}).get("time") or {}
    start = time.get("start_datetime")
    end = time.get("end_datetime")
    if not start or not end:
        raise ValueError(
            "a steady phase averages the record over one steady period and reads its "
            "span from [simulation.time], which declares no start_datetime/end_datetime "
            "here. Write them, or name the span in the phase's steady_window "
            "([calibration.protocol].steady_window when a protocol writes the phase)."
        )
    return (
        _canonical_instant(start, "simulation.time.start_datetime"),
        _canonical_instant(end, "simulation.time.end_datetime"),
    )


__all__ = ["phase_overrides", "regime_overrides"]
