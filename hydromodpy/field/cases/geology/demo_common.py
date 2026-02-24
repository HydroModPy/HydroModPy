"""
Shared helpers for geology demo launchers.

This module centralizes repeated demo concerns:
- local path resolution inside `field/cases/geology`,
- default output-path handling (`outputs/...` for relative names),
- axis tick formatting for projected coordinates (m -> km),
- local square clipping utilities,
- figure saving.
"""

from __future__ import annotations

from pathlib import Path

from matplotlib.ticker import FuncFormatter, MaxNLocator
from shapely.geometry import box


def resolve_case_path(path_like):
    """
    Resolve a path relative to this geology-case directory.
    """
    raw = Path(str(path_like))
    if raw.is_absolute():
        return raw
    return (Path(__file__).resolve().parent / raw).resolve()


def resolve_output_path(path_like, *, default_file: str):
    """
    Resolve output path, routing bare filenames into `outputs/`.

    Examples
    --------
    - "my_fig.png" -> ".../geology/outputs/my_fig.png"
    - "outputs/a.png" -> ".../geology/outputs/a.png"
    - "C:/tmp/a.png" -> "C:/tmp/a.png"
    """
    raw_text = str(path_like).strip()
    raw = Path(raw_text) if raw_text else Path(str(default_file))
    if raw.is_absolute():
        return raw
    if len(raw.parts) == 1:
        raw = Path("outputs") / raw
    return resolve_case_path(raw)


def format_axes_ticks_km(ax):
    """
    Improve axis tick readability for projected coordinates (meters -> km).
    """
    km_formatter = FuncFormatter(lambda value, _pos: f"{value / 1000.0:.0f}")
    ax.xaxis.set_major_locator(MaxNLocator(nbins=6, min_n_ticks=4))
    ax.yaxis.set_major_locator(MaxNLocator(nbins=6, min_n_ticks=4))
    ax.xaxis.set_major_formatter(km_formatter)
    ax.yaxis.set_major_formatter(km_formatter)
    ax.tick_params(axis="x", labelrotation=30, labelsize=9)
    ax.tick_params(axis="y", labelsize=9)
    ax.set_xlabel("x [km]")
    ax.set_ylabel("y [km]")


def clip_square_window(gdf, *, center_x: float, center_y: float, window_km: float):
    """
    Clip one GeoDataFrame to a square window centered at (center_x, center_y).
    """
    side_m = float(window_km) * 1000.0
    if side_m <= 0.0:
        raise ValueError("window_km must be > 0")
    half = 0.5 * side_m
    win = box(
        float(center_x) - half,
        float(center_y) - half,
        float(center_x) + half,
        float(center_y) + half,
    )

    bbox_gdf = gdf.__class__(geometry=[win], crs=gdf.crs)
    clipped = gdf[gdf.intersects(win)].copy()
    if clipped.empty:
        raise ValueError(
            "Selected window does not intersect geology features. "
            "Choose another center/window."
        )
    clipped = clipped.clip(bbox_gdf)
    if clipped.empty:
        raise ValueError(
            "Geology became empty after clipping. "
            "Choose another center/window."
        )
    return clipped, win


def save_figure(fig, output_path):
    """
    Save a matplotlib figure and ensure output directory exists.
    """
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, bbox_inches="tight")
    return output
