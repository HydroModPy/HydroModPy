"""Matplotlib backend lifecycle and figure saving.

The :class:`BackendManager` context manager switches matplotlib to a
headless backend for non-interactive runs and tears down every open
figure on exit. Use it around a batch of figure calls to keep CI
deterministic.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from matplotlib.figure import Figure as MplFigure


class BackendManager:
    """Scope matplotlib backend and cleanup to a ``with`` block."""

    def __init__(self, interactive: bool = False, dpi: int = 150) -> None:
        self.interactive = interactive
        self.dpi = dpi
        self._previous_backend: str | None = None

    def __enter__(self) -> "BackendManager":
        import matplotlib

        self._previous_backend = matplotlib.get_backend()
        target = self._previous_backend if self.interactive else "Agg"
        if target.lower() != self._previous_backend.lower():
            matplotlib.use(target, force=True)
        matplotlib.rcParams["figure.dpi"] = self.dpi
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        import matplotlib
        import matplotlib.pyplot as plt

        plt.close("all")
        if self._previous_backend is not None:
            current = matplotlib.get_backend()
            if current.lower() != self._previous_backend.lower():
                try:
                    matplotlib.use(self._previous_backend, force=True)
                except Exception:
                    pass


def save_figure(
    fig: "MplFigure",
    path: str | Path,
    *,
    dpi: int = 150,
    fmt: str | None = None,
) -> Path:
    """Save ``fig`` to ``path``, creating parent directories as needed."""
    p = Path(path).expanduser()
    p.parent.mkdir(parents=True, exist_ok=True)
    if fmt is not None and p.suffix.lstrip(".").lower() != fmt.lower():
        p = p.with_suffix(f".{fmt}")
    elif p.suffix == "":
        p = p.with_suffix(".png")
    fig.savefig(p, dpi=dpi, bbox_inches="tight")
    return p


__all__ = ["BackendManager", "save_figure"]
