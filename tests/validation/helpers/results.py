"""Record what a validation test measured, for the documentation.

A validation test states a measured value and the threshold it must stay
under. This module keeps both, with the reference curve when there is one,
so that ``tests/validation/conftest.py`` can write them to a JSON file at the
end of the session. The documentation page reads that file.

Recording never changes a test outcome. Outside a pytest session that
collects ``tests/validation`` (a case run by hand), every call is a no-op.
"""

from __future__ import annotations

import math
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import Any

import numpy as np

# Longest series kept per curve. The page draws a figure, not the raw output.
MAX_POINTS = 80

_CURRENT: dict[str, Any] | None = None


def new_record() -> dict[str, Any]:
    """Return an empty record for one test."""
    return {"metrics": [], "series": [], "scale": None, "case": None}


@contextmanager
def recording(record: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """Route the calls of this module to ``record`` while the block runs."""
    global _CURRENT
    previous, _CURRENT = _CURRENT, record
    try:
        yield record
    finally:
        _CURRENT = previous


def _number(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def record_metric(
    name: str,
    value: Any,
    threshold: Any,
    *,
    op: str = "<",
    unit: str = "",
    ideal: float | None = None,
) -> None:
    """Keep one checked metric: its value, the threshold and the comparison.

    ``op`` is the comparison the test asserts (``<``, ``<=``, ``>``, ``>=``).
    ``ideal`` is the value a perfect result gives, for a metric that must stay
    above its threshold (1 for a Nash-Sutcliffe efficiency). The page uses it
    to say how much of the allowed margin a run used.
    """
    if _CURRENT is None:
        return
    _CURRENT["metrics"].append(
        {
            "name": str(name),
            "value": _number(value),
            "threshold": _number(threshold),
            "op": op,
            "unit": unit,
            "ideal": _number(ideal),
        }
    )


def record_scale(value: Any, label: str, unit: str = "") -> None:
    """Keep the size of the signal the thresholds are read against."""
    if _CURRENT is None:
        return
    number = _number(value)
    if number is not None and number > 0.0:
        _CURRENT["scale"] = {"value": number, "label": label, "unit": unit}


def record_case(case_id: str | None) -> None:
    """Name the benchmark case a test ran, when one file runs several."""
    if _CURRENT is not None and case_id:
        _CURRENT["case"] = str(case_id)


def _thin(values: np.ndarray, keep: np.ndarray) -> list[float | None]:
    return [_number(f"{v:.6g}") for v in values[keep]]


def record_series(
    name: str,
    x: Sequence[float] | np.ndarray,
    reference: Sequence[float] | np.ndarray,
    simulated: Sequence[float] | np.ndarray,
    *,
    x_label: str,
    y_label: str,
    log: bool = False,
) -> None:
    """Keep one curve of the reference and the simulation, thinned for a figure.

    ``log`` asks the page to draw both axes on a log scale.
    """
    if _CURRENT is None:
        return
    xs = np.asarray(x, dtype=float).ravel()
    ref = np.asarray(reference, dtype=float).ravel()
    sim = np.asarray(simulated, dtype=float).ravel()
    if not (xs.size == ref.size == sim.size) or xs.size < 2:
        return
    keep = np.unique(np.linspace(0, xs.size - 1, min(MAX_POINTS, xs.size)).round().astype(int))
    _CURRENT["series"].append(
        {
            "name": name,
            "x_label": x_label,
            "y_label": y_label,
            "x": _thin(xs, keep),
            "reference": _thin(ref, keep),
            "simulated": _thin(sim, keep),
            "log": bool(log),
        }
    )


def _range(values: np.ndarray) -> float:
    finite = values[np.isfinite(values)]
    return float(finite.max() - finite.min()) if finite.size else 0.0


def record_comparison(comparison: Any) -> None:
    """Keep the curve, the signal size and the case of a case comparison payload.

    The payloads of ``validation_cases`` share field names. A steady profile
    has ``x`` (or a radius), ``analytical_profile`` and ``numerical_profile``.
    A transient profile has ``analytical_profiles`` and ``numerical_profiles``,
    one row per output time: the last row is kept. A recession has the two
    discharge series against ``elapsed_days``.
    """
    if _CURRENT is None:
        return
    metadata = getattr(comparison, "metadata", None) or {}
    record_case(metadata.get("case_id"))
    get = lambda name: getattr(comparison, name, None)  # noqa: E731

    if get("analytical_discharge_m3_s") is not None:
        ref = np.asarray(get("analytical_discharge_m3_s"), dtype=float)
        record_series(
            "Discharge at the outlet",
            get("elapsed_days"),
            ref,
            get("numerical_discharge_m3_s"),
            x_label="time (d)",
            y_label="discharge (m3/s)",
        )
        record_scale(np.nanmax(np.abs(ref)), "initial discharge of the reference", "m3/s")
        return

    if get("analytical_drawdown") is not None and get("numerical_drawdown_mean") is not None:
        ref_all = np.asarray(get("analytical_drawdown"), dtype=float)
        sim_all = np.asarray(get("numerical_drawdown_mean"), dtype=float)
        radius = float(np.asarray(get("monitor_radii_m"), dtype=float)[0])
        record_series(
            f"Drawdown at {radius:.0f} m from the well",
            get("elapsed_days"),
            ref_all[:, 0],
            sim_all[:, 0],
            x_label="time (d)",
            y_label="drawdown (m)",
        )
        record_scale(np.nanmax(np.abs(ref_all)), "largest drawdown of the reference", "m")
        return

    if get("analytical_interception_x_by_time") is not None:
        ref = np.asarray(get("analytical_interception_x_by_time"), dtype=float)
        record_series(
            "Seepage front position",
            get("elapsed_days"),
            ref,
            get("numerical_interception_x_by_time"),
            x_label="time (d)",
            y_label="front position (m)",
        )
        record_scale(_range(ref), "travel of the reference front", "m")
        return

    if get("analytical_profiles") is not None and get("numerical_profiles") is not None:
        ref_all = np.asarray(get("analytical_profiles"), dtype=float)
        sim_all = np.asarray(get("numerical_profiles"), dtype=float)
        record_series(
            "Head profile at the last output time",
            get("x"),
            ref_all[-1],
            sim_all[-1],
            x_label="x (m)",
            y_label="head (m)",
        )
        record_scale(_range(ref_all), "head range of the reference over space and time", "m")
        return

    if get("analytical_profile") is not None and get("numerical_profile") is not None:
        ref = np.asarray(get("analytical_profile"), dtype=float)
        radial = get("annular_radius") is not None
        x = get("annular_radius") if radial else get("x")
        record_series(
            "Head profile",
            x,
            ref,
            get("numerical_profile"),
            x_label="radius (m)" if radial else "x (m)",
            y_label="head (m)",
        )
        record_scale(_range(ref), "head range of the reference", "m")
        return

    if get("analytical_head_profile") is not None and get("x_m") is not None:
        ref = np.asarray(get("analytical_head_profile"), dtype=float)
        sim = np.asarray(get("watertable"), dtype=float)
        if sim.ndim == 2:
            sim = sim.mean(axis=0)
        record_series(
            "Water table",
            get("x_m"),
            ref,
            sim,
            x_label="x (m)",
            y_label="head (m)",
        )
        record_scale(_range(ref), "head range of the reference", "m")


__all__ = [
    "MAX_POINTS",
    "new_record",
    "record_case",
    "record_comparison",
    "record_metric",
    "record_scale",
    "record_series",
    "recording",
]
