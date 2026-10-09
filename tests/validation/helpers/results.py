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
    return {
        "metrics": [],
        "series": [],
        "scale": None,
        "case": None,
        "samples": [],
        "maps": [],
        "spacetime": [],
    }


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


# Most evaluated points kept per method. The page draws a figure, not the trace.
MAX_SAMPLES = 200


def record_samples(
    name: str,
    parameters: list[str],
    points: Sequence[Sequence[float]] | np.ndarray,
    objective: Sequence[float] | np.ndarray,
    truth: dict[str, float],
) -> None:
    """Keep the points one calibration method evaluated, thinned for a figure.

    ``points`` has one row per evaluation and one column per name in
    ``parameters``. ``objective`` is the cost of each row. Rows with a
    non-finite cost are dropped. At most ``MAX_SAMPLES`` rows are kept, evenly
    spaced in evaluation order, the best one always included. ``truth`` maps
    each parameter to the value that produced the observations.
    """
    if _CURRENT is None:
        return
    pts = np.asarray(points, dtype=float)
    obj = np.asarray(objective, dtype=float).ravel()
    if pts.ndim != 2 or pts.shape[0] != obj.size or pts.shape[1] != len(parameters):
        return
    finite = np.isfinite(obj) & np.isfinite(pts).all(axis=1)
    pts, obj = pts[finite], obj[finite]
    if obj.size == 0:
        return
    keep = np.unique(np.linspace(0, obj.size - 1, min(MAX_SAMPLES, obj.size)).round().astype(int))
    keep = np.unique(np.append(keep, int(np.argmin(obj))))
    _CURRENT["samples"].append(
        {
            "name": str(name),
            "parameters": [str(p) for p in parameters],
            "truth": {str(k): _number(v) for k, v in truth.items()},
            "n_evaluated": int(obj.size),
            "points": [[_number(f"{v:.6g}") for v in row] for row in pts[keep]],
            "objective": _thin(obj, keep),
        }
    )


# Largest grid of the space-time error kept per run.
MAX_SPACETIME_X = 40
MAX_SPACETIME_T = 30


def _sig(values: np.ndarray, digits: int = 6) -> list[float | None]:
    return [_number(f"{v:.{digits}g}") for v in values]


def record_spacetime(
    name: str,
    x: Sequence[float] | np.ndarray,
    times: Sequence[float] | np.ndarray,
    reference: np.ndarray,
    simulated: np.ndarray,
    *,
    x_label: str,
    t_label: str,
    unit: str,
) -> None:
    """Keep simulated minus reference on an (x, time) grid, thinned for a figure.

    ``reference`` and ``simulated`` have one row per output time and one column
    per ``x``. At most ``MAX_SPACETIME_X`` columns and ``MAX_SPACETIME_T`` rows
    are kept, evenly spaced. The error is stored with 4 significant digits.
    """
    if _CURRENT is None:
        return
    xs = np.asarray(x, dtype=float).ravel()
    ts = np.asarray(times, dtype=float).ravel()
    ref = np.asarray(reference, dtype=float)
    sim = np.asarray(simulated, dtype=float)
    if ref.shape != (ts.size, xs.size) or sim.shape != ref.shape or xs.size < 2 or ts.size < 2:
        return
    ix = np.unique(np.linspace(0, xs.size - 1, min(MAX_SPACETIME_X, xs.size)).round().astype(int))
    it = np.unique(np.linspace(0, ts.size - 1, min(MAX_SPACETIME_T, ts.size)).round().astype(int))
    error = (sim - ref)[np.ix_(it, ix)]
    _CURRENT["spacetime"].append(
        {
            "name": str(name),
            "x_label": x_label,
            "t_label": t_label,
            "unit": unit,
            "x": _sig(xs[ix]),
            "t": _sig(ts[it]),
            "error": [_sig(row, 3) for row in error],
        }
    )


def _grid_of(polygons: Any) -> tuple[np.ndarray, np.ndarray, np.ndarray] | None:
    """Edges and the (row, column) of each cell when the cells tile a regular grid.

    A regular grid may come as ``{"x_edges": [...], "y_edges": [...]}``, row
    major, or as axis-aligned rectangles whose corners fall on shared edges.
    Returns ``None`` for any other mesh.
    """
    if isinstance(polygons, dict):
        xe = np.asarray(polygons.get("x_edges"), dtype=float).ravel()
        ye = np.asarray(polygons.get("y_edges"), dtype=float).ravel()
        if xe.size < 2 or ye.size < 2:
            return None
        rows, cols = np.divmod(np.arange((xe.size - 1) * (ye.size - 1)), xe.size - 1)
        return xe, ye, np.column_stack([rows, cols])
    boxes = []
    for poly in polygons:
        pts = np.round(np.asarray(poly, dtype=float).reshape(-1, 2), 2)
        xs, ys = np.unique(pts[:, 0]), np.unique(pts[:, 1])
        if pts.shape[0] != 4 or xs.size != 2 or ys.size != 2:
            return None
        boxes.append((xs[0], xs[1], ys[0], ys[1]))
    if not boxes:
        return None
    box = np.array(boxes)
    xe = np.unique(box[:, :2])
    ye = np.unique(box[:, 2:])
    cols = np.searchsorted(xe, box[:, 0])
    rows = np.searchsorted(ye, box[:, 2])
    one_cell = (xe[np.minimum(cols + 1, xe.size - 1)] == box[:, 1]) & (
        ye[np.minimum(rows + 1, ye.size - 1)] == box[:, 3]
    )
    if not one_cell.all():
        return None
    return xe, ye, np.column_stack([rows, cols])


def _mesh_of(polygons: Any) -> tuple[np.ndarray, list[list[int]]] | None:
    """Shared vertices and one index list per cell, rounded to 0.1 m."""
    index: dict[tuple[float, float], int] = {}
    faces = []
    for poly in polygons:
        pts = np.round(np.asarray(poly, dtype=float).reshape(-1, 2), 1)
        faces.append([index.setdefault((float(x), float(y)), len(index)) for x, y in pts])
    if not faces:
        return None
    return np.array(list(index)), faces


def record_map(
    name: str,
    polygons: Any,
    simulated: Sequence[float] | np.ndarray,
    reference: Sequence[float] | np.ndarray,
    *,
    overlay: dict[str, Any] | None = None,
) -> None:
    """Keep the plan-view error of one run: simulated minus reference, per cell.

    ``polygons`` is one (n, 2) array per cell in local metres, or a regular grid
    as ``{"x_edges", "y_edges"}``. The values have one entry per cell, NaN for
    sea or inactive cells. A regular grid is kept as its edges and a row-major
    error array (key ``grid``). Any other mesh keeps shared vertices and one
    vertex index list per cell. The error keeps 2 significant digits: the page
    draws a map, not the raw output. ``overlay`` may carry ``coast_circle``
    ``[cx, cy, radius]`` or ``well`` ``[x, y]``, in metres.
    """
    if _CURRENT is None:
        return
    sim = np.asarray(simulated, dtype=float).ravel()
    ref = np.asarray(reference, dtype=float).ravel()
    if sim.size != ref.size:
        return
    error = sim - ref
    keep = {}
    for key in ("coast_circle", "well"):
        value = (overlay or {}).get(key)
        if value is not None:
            keep[key] = _sig(np.asarray(value, dtype=float).ravel(), 6)
    entry: dict[str, Any] = {"name": str(name), "overlay": keep}
    grid = _grid_of(polygons)
    if grid is not None and len(grid[2]) == error.size:
        xe, ye, where = grid
        full = np.full((ye.size - 1, xe.size - 1), np.nan)
        full[where[:, 0], where[:, 1]] = error
        entry["grid"] = {"x_edges": _sig(xe, 8), "y_edges": _sig(ye, 8)}
        entry["error"] = _sig(full.ravel(), 2)
    else:
        mesh = _mesh_of(polygons)
        if mesh is None or len(mesh[1]) != error.size:
            return
        vertices, faces = mesh
        entry["vertices"] = [_sig(v, 8) for v in vertices]
        entry["faces"] = faces
        entry["error"] = _sig(error, 2)
    _CURRENT["maps"].append(entry)


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

    if get("map_cell_polygons") is not None:
        record_map(
            "Head error map",
            get("map_cell_polygons"),
            get("map_simulated"),
            get("map_reference"),
            overlay=get("map_overlay"),
        )

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
        times = get("elapsed_days")
        if times is not None:
            record_spacetime(
                "Head error over space and time",
                get("x"),
                times,
                ref_all,
                sim_all,
                x_label="x (m)",
                t_label="time (d)",
                unit="m",
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
    "MAX_SAMPLES",
    "new_record",
    "record_case",
    "record_comparison",
    "record_map",
    "record_metric",
    "record_samples",
    "record_scale",
    "record_series",
    "record_spacetime",
    "recording",
]
