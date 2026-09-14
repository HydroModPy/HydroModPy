"""Shared rendering assertions used across figure tests.

Several figure tests need to know whether a drawn colour reads as light or
dark on paper, to check that text or markers placed on top stay legible.
"""

from __future__ import annotations


def relative_luminance(color: str) -> float:
    """Perceived brightness of one colour, the quantity a greyscale print keeps."""
    from matplotlib.colors import to_rgb

    channels = [
        value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
        for value in to_rgb(color)
    ]
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]
