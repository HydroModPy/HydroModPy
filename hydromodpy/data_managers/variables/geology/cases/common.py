"""Shared helpers for geology demo launchers."""

from __future__ import annotations

from pathlib import Path

from matplotlib.ticker import FuncFormatter, MaxNLocator
from shapely.geometry import box

from hydromodpy.support.units import parse_length_to_m


def resolve_case_path(path_like):
    """Resolve a path relative to this geology-case directory."""
    raw = Path(str(path_like))
    if raw.is_absolute():
        return raw
    return (Path(__file__).resolve().parent / raw).resolve()


def resolve_output_path(path_like, *, default_file: str):
    """Resolve output path, routing bare filenames into ``outputs/``."""
    raw_text = str(path_like).strip()
    raw = Path(raw_text) if raw_text else Path(str(default_file))
    if raw.is_absolute():
        return raw
    if len(raw.parts) == 1:
        raw = Path("outputs") / raw
    return resolve_case_path(raw)


def format_axes_ticks_km(ax):
    """Improve axis tick readability for projected coordinates (meters -> km)."""
    km_formatter = FuncFormatter(lambda value, _pos: f"{value / 1000.0:.0f}")
    ax.xaxis.set_major_locator(MaxNLocator(nbins=6, min_n_ticks=4))
    ax.yaxis.set_major_locator(MaxNLocator(nbins=6, min_n_ticks=4))
    ax.xaxis.set_major_formatter(km_formatter)
    ax.yaxis.set_major_formatter(km_formatter)
    ax.tick_params(axis="x", labelrotation=30, labelsize=9)
    ax.tick_params(axis="y", labelsize=9)
    ax.set_xlabel("x [km]")
    ax.set_ylabel("y [km]")


def clip_square_window(
    gdf,
    *,
    center_x: float,
    center_y: float,
    window_m: float | None = None,
    window_km: float | None = None,
):
    """Clip one GeoDataFrame to a square window centered at ``(center_x, center_y)``."""
    if window_m is not None and window_km is not None:
        raise ValueError("Use either window_m or window_km, not both.")
    if window_m is None and window_km is None:
        raise ValueError("window_m or window_km must be provided.")

    raw_window = window_m if window_m is not None else window_km
    raw_default_unit = "m" if window_m is not None else "km"
    side_m = float(
        parse_length_to_m(
            raw_window,
            default_unit=raw_default_unit,
            label="window",
        )
    )
    if side_m <= 0.0:
        raise ValueError("window must be > 0")

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
    """Save a matplotlib figure and ensure output directory exists."""
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, bbox_inches="tight")
    return output
