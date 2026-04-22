"""Content-addressable params_hash cache.

Two calls with the same **resolved, transformed** parameters produce the same
SHA-256. The cache lets an optimizer skip re-running an already-evaluated
point, and lets ``calibration_iterations`` dedupe across sessions.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping


def canonical_json(values: Mapping[str, float], *, precision: int = 12) -> str:
    """Deterministic JSON for a dict of floats.

    Keys are sorted; values are rounded to ``precision`` significant digits
    so floating-point noise below that threshold yields the same hash.
    """
    rounded: dict[str, float] = {}
    for k in sorted(values):
        v = float(values[k])
        if math.isnan(v) or math.isinf(v):
            rounded[k] = v
        else:
            rounded[k] = round(v, precision) if v == 0.0 else _round_sig(v, precision)
    return json.dumps(rounded, sort_keys=True, separators=(",", ":"))


def _round_sig(v: float, digits: int) -> float:
    if v == 0.0:
        return 0.0
    magnitude = math.floor(math.log10(abs(v)))
    return round(v, digits - 1 - magnitude)


def params_hash(values: Mapping[str, float], *, precision: int = 12) -> str:
    """SHA-256 of the canonical JSON of ``values``."""
    payload = canonical_json(values, precision=precision).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class ParamsHashCache:
    """In-memory cache mapping params_hash → sim_id.

    Thin wrapper; persistence is handled by the DuckDB ``calibration_iterations``
    table (column ``params_hash``). This class is for the current run only.
    """

    def __init__(self) -> None:
        self._hits: dict[str, str] = {}

    def __contains__(self, key: str) -> bool:
        return key in self._hits

    def get(self, key: str) -> str | None:
        return self._hits.get(key)

    def put(self, key: str, sim_id: str) -> None:
        self._hits[key] = sim_id

    def __len__(self) -> int:
        return len(self._hits)


__all__ = ["params_hash", "canonical_json", "ParamsHashCache"]
