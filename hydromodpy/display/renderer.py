"""Matplotlib backend lifecycle and figure saving."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from matplotlib.figure import Figure as MplFigure


@contextmanager
def matplotlib_backend(*, interactive: bool = False, dpi: int = 150) -> Iterator[None]:
    """Scope matplotlib backend and cleanup to a ``with`` block."""
    import matplotlib

    previous_backend = matplotlib.get_backend()
    target = previous_backend if interactive else "Agg"
    if target.lower() != previous_backend.lower():
        matplotlib.use(target, force=True)
    rc_context = matplotlib.rc_context()
    try:
        with rc_context:
            matplotlib.rcParams["figure.dpi"] = dpi
            yield
    finally:
        import matplotlib.pyplot as plt

        plt.close("all")
        current = matplotlib.get_backend()
        if current.lower() != previous_backend.lower():
            try:
                matplotlib.use(previous_backend, force=True)
            except Exception:
                pass


def save_figure(
    fig: MplFigure,
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


__all__ = ["matplotlib_backend", "save_figure"]
