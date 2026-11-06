"""Shared rendering assertions used across figure tests.

Several figure tests need to know whether a drawn color reads as light or
dark on paper, to check that text or markers placed on top stay legible.
"""

from __future__ import annotations


def relative_luminance(color: str) -> float:
    """Perceived brightness of one color, the quantity a grayscale print keeps."""
    from matplotlib.colors import to_rgb

    channels = [
        value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
        for value in to_rgb(color)
    ]
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def lightness(rgb) -> float:
    """Return the CIE L* of one RGB triple, which is what grayscale keeps."""
    channels = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb[:3]]
    y = 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]
    return 116.0 * y ** (1 / 3) - 16.0 if y > 0.008856 else 903.3 * y


def labelled_patch(ax, prefix: str):
    return next(item for item in ax.patches if str(item.get_label()).startswith(prefix))


def rgba(color: str):
    from matplotlib.colors import to_rgba

    return to_rgba(color)
