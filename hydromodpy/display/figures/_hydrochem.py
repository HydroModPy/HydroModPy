"""The sample table the Piper, Schoeller and Stiff diagrams read.

A diagram takes either a DataFrame of samples or a run that stores a
``hydrochemistry`` series. The three diagrams read and refuse it the same way.
"""

from __future__ import annotations

from typing import Any

import pandas as pd


def hydrochem_frame(source: Any, figure: str) -> pd.DataFrame:
    """Return the hydrochemistry samples of ``source``, a DataFrame or a run.

    Raises ValueError when the run stores no such series and TypeError for a
    source that is neither.
    """
    if isinstance(source, pd.DataFrame):
        return source
    if hasattr(source, "timeseries"):
        try:
            return source.timeseries("hydrochemistry")
        except Exception as exc:
            raise ValueError(f"{figure}: no hydrochemistry data available") from exc
    raise TypeError(f"{figure}: cannot read hydrochemistry data from {type(source)!r}")


def missing_samples_reason(source: Any, figure: str) -> str | None:
    """Say why ``source`` gives a diagram no sample to draw, or None when it gives some."""
    try:
        samples = hydrochem_frame(source, figure)
    except (TypeError, ValueError):
        return "run holds no hydrochemistry series"
    if len(samples) == 0:
        return "run holds no hydrochemistry sample"
    return None
