"""Shared utilities for the model-calibration launcher package."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np


def jsonable(value: Any) -> Any:
    """Convert common runtime values to JSON-friendly Python values.

    Handles numpy scalars/arrays, Path objects, non-finite floats,
    and nested dicts/lists. Non-finite floats are mapped to ``None``
    so downstream ``json.dumps`` never raises on NaN/Inf.
    """
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, np.ndarray):
        return [jsonable(item) for item in value.tolist()]
    if isinstance(value, np.generic):
        return jsonable(value.item())
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    try:
        json.dumps(value)
    except TypeError:
        return repr(value)
    return value
