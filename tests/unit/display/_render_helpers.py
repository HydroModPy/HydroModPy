"""Shared rendering assertions used across figure tests.

Several figure tests need to know whether a drawn color reads as light or
dark on paper, to check that text or markers placed on top stay legible.
"""

from __future__ import annotations

from hydromodpy.display.style import relative_luminance


def labelled_patch(ax, prefix: str):
    return next(item for item in ax.patches if str(item.get_label()).startswith(prefix))


def rgba(color: str):
    from matplotlib.colors import to_rgba

    return to_rgba(color)
