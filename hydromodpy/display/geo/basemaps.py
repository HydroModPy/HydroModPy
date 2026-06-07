"""Optional web-tile basemaps via ``contextily``.

``contextily`` is not a hard dependency of HydroModPy. If it is missing,
:func:`add_basemap` silently no-ops so that figures can still be rendered
in offline or CI environments.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from matplotlib.axes import Axes


def add_basemap(
    ax: Axes,
    *,
    crs: str | None = None,
    source: str | None = None,
    alpha: float = 1.0,
) -> bool:
    """Add a tile basemap to ``ax``. Returns True on success, False otherwise."""
    try:
        import contextily as cx
    except ImportError:
        return False
    tile_source = None
    if source is not None:
        tile_source = getattr(cx.providers, source, None) or source
    try:
        cx.add_basemap(ax, crs=crs, source=tile_source, alpha=alpha)
    except Exception:
        return False
    return True


__all__ = ["add_basemap"]
