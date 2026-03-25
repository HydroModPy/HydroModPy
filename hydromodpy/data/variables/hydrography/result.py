"""Hydrography load result."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class HydrographyResult:
    """Result of hydrography loading: clipped vector, rasterised TIF, and array.

    ``streams`` is *None* when the input was a pre-rasterised TIF (no vector layer).
    """

    streams: str | None
    tif_streams: str
    streams_array: np.ndarray
