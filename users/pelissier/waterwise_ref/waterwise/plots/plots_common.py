from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt

from waterwise.plots.parameters_plots import (
    RasterRef,
    compute_hillshade,
    extent_from_transform,
    read_border,
    read_glaciers,
    save_stack_pngs,
)


def ensure_parent_dir(path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def ensure_dir(path: str | Path) -> Path:
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_figure(fig, path: str | Path, *, dpi: int = 150, bbox_inches: str = "tight") -> Path:
    path = ensure_parent_dir(path)
    fig.savefig(path, dpi=dpi, bbox_inches=bbox_inches)
    plt.close(fig)
    return path


__all__ = [
    "RasterRef",
    "compute_hillshade",
    "extent_from_transform",
    "read_border",
    "read_glaciers",
    "save_stack_pngs",
    "ensure_parent_dir",
    "ensure_dir",
    "save_figure",
]
