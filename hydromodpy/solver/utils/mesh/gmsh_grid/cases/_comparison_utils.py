"""Shared helper functions for comparison scripts (2D and 3D).

This module consolidates utility functions that were duplicated across
``comparison_cartesian_vs_gmsh_2d/run_compare.py`` and
``comparison_cartesian_vs_gmsh_3d/run_compare.py``.
"""

from __future__ import annotations

import json
from pathlib import Path

from matplotlib import pyplot as plt
import numpy as np

from hydromodpy.solver.utils.mesh.gmsh_grid.plotting_utils import (
    ensure_interactive_backend_for_show,
)
from hydromodpy.solver.utils.mesh.plot_window_utils import maximize_figure_windows


# ---------------------------------------------------------------------------
# Path / IO helpers
# ---------------------------------------------------------------------------


def resolve_config_path(raw_config: str | Path, *, caller_file: str | Path | None = None) -> Path:
    """Resolve a config TOML path relative to CWD or the caller's script dir.

    Search order: absolute path, CWD-relative, then caller-script-relative.
    Pass *caller_file* (typically ``__file__``) so that the fallback lookup
    searches relative to the calling script rather than this shared module.
    """
    candidate = Path(raw_config).expanduser()
    if candidate.is_absolute() and candidate.exists():
        return candidate.resolve()

    cwd_candidate = candidate.resolve()
    if cwd_candidate.exists():
        return cwd_candidate

    # Fallback: relative to the caller's directory.
    base = Path(caller_file).resolve().parent if caller_file is not None else Path(__file__).resolve().parent
    script_candidate = (base / candidate).resolve()
    if script_candidate.exists():
        return script_candidate

    raise FileNotFoundError(f"Config TOML not found: '{raw_config}'")


def resolve_output_dir(raw_output_dir: str | Path, *, default_base: Path) -> Path:
    """Return an absolute, existing output directory."""
    path = Path(raw_output_dir).expanduser()
    if not path.is_absolute():
        path = (default_base / path).resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_json(path: Path, payload: dict) -> None:
    """Write *payload* as indented JSON to *path*."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2, ensure_ascii=True)
        stream.write("\n")


# ---------------------------------------------------------------------------
# Display helper
# ---------------------------------------------------------------------------


def show_saved_images_blocking(
    image_paths: list[Path],
    *,
    figsize_per_image: tuple[float, float] = (7.0, 4.7),
) -> None:
    """Open a blocking matplotlib window showing *image_paths* in a grid."""
    valid_paths = [Path(p) for p in image_paths if Path(p).exists()]
    if not valid_paths:
        return
    ensure_interactive_backend_for_show()
    n_images = len(valid_paths)
    n_cols = min(2, n_images)
    n_rows = int(np.ceil(n_images / float(n_cols)))
    fig, axes = plt.subplots(
        n_rows,
        n_cols,
        figsize=(figsize_per_image[0] * n_cols, figsize_per_image[1] * n_rows),
        dpi=120,
        squeeze=False,
    )
    axes_flat = list(axes.reshape(-1))
    for idx, ax in enumerate(axes_flat):
        if idx >= n_images:
            ax.axis("off")
            continue
        image_path = valid_paths[idx]
        img = plt.imread(image_path)
        ax.imshow(img)
        ax.axis("off")
        ax.set_title(image_path.name, fontsize=11)
    plt.tight_layout()
    plt.ioff()
    maximize_figure_windows(fig)
    plt.show(block=True)
    plt.close(fig)


# ---------------------------------------------------------------------------
# Numeric helpers
# ---------------------------------------------------------------------------


def round_float(value: float, ndigits: int = 12) -> float:
    """Round a scalar to *ndigits* decimal places."""
    return round(float(value), ndigits)


def rounded_list(values, *, ndigits: int = 12) -> list[float]:
    """Flatten *values* to a 1-D float list, rounding each element."""
    return [
        round_float(v, ndigits=ndigits)
        for v in np.asarray(values, dtype=float).reshape(-1)
    ]


def array_stats(arr) -> dict[str, float]:
    """Return min / max / mean / sum of finite values in *arr*.

    Raises :class:`ValueError` when no finite values exist.
    """
    values = np.asarray(arr, dtype=float)
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        raise ValueError("Cannot compute stats on an array without finite values")
    return {
        "min": round_float(np.min(finite)),
        "max": round_float(np.max(finite)),
        "mean": round_float(np.mean(finite)),
        "sum": round_float(np.sum(finite)),
    }


def value_quantiles(
    arr, *, quantiles=(0.05, 0.25, 0.50, 0.75, 0.95)
) -> dict[str, float]:
    """Return labelled quantiles (e.g. ``q05``, ``q50``) for finite values."""
    values = np.asarray(arr, dtype=float)
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        raise ValueError("Cannot compute quantiles on an array without finite values")
    payload: dict[str, float] = {}
    for q in quantiles:
        key = f"q{int(round(float(q) * 100.0)):02d}"
        payload[key] = round_float(np.quantile(finite, float(q)))
    return payload


def signature_head(arr, *, n: int = 8) -> list[float]:
    """Return the first *n* elements of the flattened array, rounded."""
    flat = np.asarray(arr, dtype=float).reshape(-1)
    return [round_float(v) for v in flat[:n]]


# ---------------------------------------------------------------------------
# Mesh geometry helpers
# ---------------------------------------------------------------------------


def polygon_area(vertices) -> float:
    """Shoelace formula for a simple polygon given an (N, 2+) vertex array."""
    xy = np.asarray(vertices, dtype=float)
    x = xy[:, 0]
    y = xy[:, 1]
    return 0.5 * float(np.abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))))


def mesh_footprint_area(mesh) -> float:
    """Total planar area of all cells in *mesh*."""
    return round_float(sum(polygon_area(cell.vertices) for cell in mesh.cells))


def mesh_bounds_xy(mesh) -> list[float]:
    """Return ``[xmin, ymin, xmax, ymax]`` for *mesh*.

    Uses the ``bounds`` attribute when available (handling both 4- and 6-element
    forms), falling back to ``x_plot`` / ``y_plot`` arrays.
    """
    if hasattr(mesh, "bounds"):
        bounds = getattr(mesh, "bounds")
        if len(bounds) >= 4:
            if len(bounds) == 4:
                return [round_float(v, ndigits=6) for v in bounds]
            return [
                round_float(bounds[0], ndigits=6),
                round_float(bounds[1], ndigits=6),
                round_float(bounds[3], ndigits=6),
                round_float(bounds[4], ndigits=6),
            ]
    x = np.asarray(getattr(mesh, "x_plot"), dtype=float)
    y = np.asarray(getattr(mesh, "y_plot"), dtype=float)
    return [
        round_float(np.nanmin(x), ndigits=6),
        round_float(np.nanmin(y), ndigits=6),
        round_float(np.nanmax(x), ndigits=6),
        round_float(np.nanmax(y), ndigits=6),
    ]


def mesh_centroids_flat(mesh) -> tuple[np.ndarray, np.ndarray]:
    """Return flat (1-D) centroid x and y arrays for *mesh*."""
    cx, cy = mesh.cell_centroids()
    return np.asarray(cx, dtype=float).reshape(-1), np.asarray(cy, dtype=float).reshape(
        -1
    )


def nearest_cell_index(mesh, *, x: float, y: float) -> tuple[int, tuple[float, float]]:
    """Index of the cell whose centroid is nearest to *(x, y)*."""
    cx, cy = mesh_centroids_flat(mesh)
    distance = np.square(cx - float(x)) + np.square(cy - float(y))
    idx = int(np.argmin(distance))
    return idx, (float(cx[idx]), float(cy[idx]))


def shared_bounds(bounds_a: list[float], bounds_b: list[float]) -> list[float]:
    """Intersect two ``[xmin, ymin, xmax, ymax]`` bounding boxes.

    Falls back to the midpoint of each edge when the boxes do not overlap.
    """
    xmin = max(float(bounds_a[0]), float(bounds_b[0]))
    ymin = max(float(bounds_a[1]), float(bounds_b[1]))
    xmax = min(float(bounds_a[2]), float(bounds_b[2]))
    ymax = min(float(bounds_a[3]), float(bounds_b[3]))
    if xmax <= xmin or ymax <= ymin:
        return [
            round_float(0.5 * (float(bounds_a[0]) + float(bounds_b[0])), ndigits=6),
            round_float(0.5 * (float(bounds_a[1]) + float(bounds_b[1])), ndigits=6),
            round_float(0.5 * (float(bounds_a[2]) + float(bounds_b[2])), ndigits=6),
            round_float(0.5 * (float(bounds_a[3]) + float(bounds_b[3])), ndigits=6),
        ]
    return [
        round_float(xmin, ndigits=6),
        round_float(ymin, ndigits=6),
        round_float(xmax, ndigits=6),
        round_float(ymax, ndigits=6),
    ]


# ---------------------------------------------------------------------------
# Layer analysis helpers
# ---------------------------------------------------------------------------


def layer_stats(values_3d) -> list[dict[str, float]]:
    """Per-layer :func:`array_stats` for a 3-D array (layer, ...)."""
    arr = np.asarray(values_3d, dtype=float)
    return [array_stats(arr[layer_idx]) for layer_idx in range(arr.shape[0])]


def layer_quantiles(values_3d) -> list[dict[str, float]]:
    """Per-layer :func:`value_quantiles` for a 3-D array (layer, ...)."""
    arr = np.asarray(values_3d, dtype=float)
    return [value_quantiles(arr[layer_idx]) for layer_idx in range(arr.shape[0])]
