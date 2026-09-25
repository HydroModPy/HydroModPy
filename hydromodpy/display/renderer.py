"""Matplotlib backend lifecycle for the length of a render."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager


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


__all__ = ["matplotlib_backend"]
