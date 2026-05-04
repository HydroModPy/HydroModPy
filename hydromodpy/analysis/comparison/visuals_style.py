"""Style helpers, palette and limit utilities for comparison visuals."""

from __future__ import annotations

import math
import re
from collections.abc import Iterable
from typing import Any

import numpy as np

_TITLE_FONT_SIZE = 11
_PANEL_TITLE_FONT_SIZE = 9
_LABEL_FONT_SIZE = 9
_TICK_FONT_SIZE = 8
_LEGEND_FONT_SIZE = 9


def _slug(value: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9]+", "_", str(value).strip().lower())
    return text.strip("_") or "item"


def _pretty_label(value: str) -> str:
    text = re.sub(r"[_]+", " ", str(value).strip())
    text = re.sub(r"\s+", " ", text).strip()
    return text[:1].upper() + text[1:] if text else "Value"


def _display_simulation_label(*, simulation_id: str, simulation_label: str) -> str:
    text = simulation_label.strip() or simulation_id.strip()
    if len(text) <= 26:
        return text
    return simulation_id.strip() or text


def _simulation_panel_title(
    *, simulation_id: str, simulation_label: str, solver: str
) -> str:
    label = _display_simulation_label(
        simulation_id=simulation_id, simulation_label=simulation_label
    )
    solver_text = str(solver).strip().lower()
    if not solver_text:
        return label
    return f"{label}\n{solver_text}"


def _style_map_axes(ax: Any) -> None:
    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_xlabel("")
    ax.set_ylabel("")
    for spine in ax.spines.values():
        spine.set_linewidth(0.6)
        spine.set_color("#9ca3af")


def _legend_ncols(n_items: int) -> int:
    if n_items <= 1:
        return 1
    if n_items <= 4:
        return 2
    return 3


def _solver_color(solver: str) -> str:
    """Return a stable color for ``solver``.

    Colors are pulled from matplotlib's ``tab10`` cycle and indexed by a
    deterministic hash of the solver name, so each name gets a consistent
    color across plots without requiring a per-solver registry.
    """
    import hashlib

    from matplotlib import colormaps

    key = str(solver).strip().lower()
    if not key:
        return "#6b7280"
    cmap = colormaps.get_cmap("tab10")
    digest = hashlib.md5(key.encode("utf-8")).digest()
    index = digest[0] % cmap.N
    return _rgba_to_hex(cmap(index))


def _rgba_to_hex(rgba: tuple[float, float, float, float]) -> str:
    r, g, b = (int(round(c * 255)) for c in rgba[:3])
    return f"#{r:02x}{g:02x}{b:02x}"


def _is_flux_like_name(name: str) -> bool:
    key = str(name).strip().lower()
    return any(
        token in key
        for token in (
            "flux",
            "drain",
            "accumulation",
            "runoff",
            "surface_excess",
            "saturation_excess",
        )
    )


def _safe_float(value: Any) -> float | None:
    if value in ("", None):
        return None
    try:
        number = float(value)
    except Exception:
        return None
    if not math.isfinite(number):
        return None
    return number


def _mask_nodata(values: np.ndarray) -> np.ndarray:
    masked = np.asarray(values, dtype=float).copy()
    if masked.size == 0:
        return masked
    for sentinel in (-9999.0, -99999.0, -999999.0):
        masked[np.isclose(masked, sentinel, rtol=0.0, atol=1.0e-6)] = np.nan
    return masked


def _finite_limits(values: Iterable[np.ndarray]) -> tuple[float, float] | None:
    arrays = [
        _mask_nodata(np.asarray(item, dtype=float)).ravel()
        for item in values
        if np.asarray(item, dtype=float).size > 0
    ]
    if not arrays:
        return None
    stacked = np.concatenate(arrays)
    finite = stacked[np.isfinite(stacked)]
    if finite.size == 0:
        return None
    return float(np.nanmin(finite)), float(np.nanmax(finite))


def _robust_limits(
    values: Iterable[np.ndarray],
    *,
    lower_percentile: float = 2.0,
    upper_percentile: float = 98.0,
) -> tuple[float, float] | None:
    arrays = [
        _mask_nodata(np.asarray(item, dtype=float)).ravel()
        for item in values
        if np.asarray(item, dtype=float).size > 0
    ]
    if not arrays:
        return None
    stacked = np.concatenate(arrays)
    finite = stacked[np.isfinite(stacked)]
    if finite.size == 0:
        return None
    if finite.size < 24:
        return float(np.nanmin(finite)), float(np.nanmax(finite))
    lower = float(np.nanpercentile(finite, lower_percentile))
    upper = float(np.nanpercentile(finite, upper_percentile))
    if not math.isfinite(lower) or not math.isfinite(upper) or lower >= upper:
        return float(np.nanmin(finite)), float(np.nanmax(finite))
    return lower, upper


def _robust_symmetric_limit(
    values: Iterable[np.ndarray],
    *,
    percentile: float = 98.0,
) -> float | None:
    arrays = [
        _mask_nodata(np.asarray(item, dtype=float)).ravel()
        for item in values
        if np.asarray(item, dtype=float).size > 0
    ]
    if not arrays:
        return None
    stacked = np.concatenate(arrays)
    finite = stacked[np.isfinite(stacked)]
    if finite.size == 0:
        return None
    if finite.size < 24:
        vmax = float(np.nanmax(np.abs(finite)))
    else:
        vmax = float(np.nanpercentile(np.abs(finite), percentile))
    if not math.isfinite(vmax) or math.isclose(vmax, 0.0):
        vmax = float(np.nanmax(np.abs(finite)))
    if not math.isfinite(vmax) or math.isclose(vmax, 0.0):
        return None
    return vmax


def _series_style(observable_name: str) -> dict[str, Any]:
    if _is_flux_like_name(observable_name):
        return {"drawstyle": "steps-post", "linewidth": 1.8, "markersize": 0.0}
    return {"linewidth": 1.8, "markersize": 3.0, "marker": "o"}


def _budget_component_label(component: str) -> str:
    labels = {
        "recharge_total_m3_s": "Recharge",
        "well_total_m3_s": "Wells",
        "drainage_total_m3_s": "Drainage",
        "surface_excess_total_m3_s": "Surface excess",
        "comparable_outflow_total_m3_s": "Comparable outflow",
        "storage_change_total_m3_s": "Storage change",
        "closure_residual_m3_s": "Closure residual",
    }
    return labels.get(component, _pretty_label(component))


def _budget_component_color(component: str) -> str:
    palette = {
        "recharge_total_m3_s": "#1f77b4",
        "well_total_m3_s": "#8c564b",
        "drainage_total_m3_s": "#ff7f0e",
        "surface_excess_total_m3_s": "#d62728",
        "comparable_outflow_total_m3_s": "#111827",
        "storage_change_total_m3_s": "#2ca02c",
        "closure_residual_m3_s": "#6b7280",
        "outlet_flux_series": "#4b5563",
    }
    return palette.get(component, "#6b7280")
