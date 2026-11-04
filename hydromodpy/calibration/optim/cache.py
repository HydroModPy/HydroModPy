"""Content-addressable calibration cache."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def canonical_json(values: Mapping[str, float], *, precision: int = 12) -> str:
    """Deterministic JSON for a dict of floats.

    Keys are sorted; values are rounded to ``precision`` significant digits
    so floating-point noise below that threshold yields the same hash.
    """
    rounded = _round_float_mapping(values, precision=precision)
    return json.dumps(rounded, sort_keys=True, separators=(",", ":"))


def _round_float_mapping(values: Mapping[str, float], *, precision: int) -> dict[str, float]:
    rounded: dict[str, float] = {}
    for key in sorted(values):
        rounded[str(key)] = _round_float(float(values[key]), precision=precision)
    return rounded


def _round_float(value: float, *, precision: int) -> float:
    if math.isnan(value) or math.isinf(value):
        return value
    return round(value, precision) if value == 0.0 else _round_sig(value, precision)


def _round_sig(v: float, digits: int) -> float:
    magnitude = math.floor(math.log10(abs(v)))
    return round(v, digits - 1 - magnitude)


def _normalize_context(value: Any, *, precision: int) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _normalize_context(value[key], precision=precision)
            for key in sorted(value, key=str)
        }
    if isinstance(value, (list, tuple)):
        return [_normalize_context(item, precision=precision) for item in value]
    if isinstance(value, (set, frozenset)):
        return [_normalize_context(item, precision=precision) for item in sorted(value, key=repr)]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, float):
        return _round_float(value, precision=precision)
    return value


CLEAR_CONTEXT_MEMBERS = frozenset({"schema", "metric_rule_version"})
"""The members of a cache context a fingerprint keeps in clear, as short words."""


def context_fingerprints(context: Mapping[str, Any], *, precision: int = 12) -> dict[str, str]:
    """Return one short fingerprint per member of a cache context.

    Each one is the sha256, cut to 16 characters, of the canonical JSON of the
    member, the same one :func:`params_hash` reads. A session keeps them to say
    which member moved; the check itself stays the hash.
    """
    fingerprints: dict[str, str] = {}
    for name in sorted(context, key=str):
        value = context[name]
        if name in CLEAR_CONTEXT_MEMBERS:
            fingerprints[str(name)] = str(value)
            continue
        text = json.dumps(
            _normalize_context(value, precision=precision), sort_keys=True, separators=(",", ":")
        )
        fingerprints[str(name)] = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    return fingerprints


def differing_members(recorded: Mapping[str, str], current: Mapping[str, str]) -> list[str]:
    """Return the members of two sets of fingerprints that differ, by name."""
    return sorted(name for name in {*recorded, *current} if recorded.get(name) != current.get(name))


def params_hash(
    values: Mapping[str, float],
    *,
    context: Mapping[str, Any] | None = None,
    precision: int = 12,
) -> str:
    """Return a SHA-256 cache key for one scientific evaluation."""
    if context is None:
        payload_text = canonical_json(values, precision=precision)
    else:
        payload = {
            "context": _normalize_context(context, precision=precision),
            "parameters": _round_float_mapping(values, precision=precision),
        }
        payload_text = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    payload_bytes = payload_text.encode("utf-8")
    digest = hashlib.sha256(payload_bytes).hexdigest()
    return digest if context is None else f"v2:{digest}"


@dataclass(frozen=True, slots=True)
class CachedEvaluation:
    """Cached cost for one parameter hash: only the numbers, never the run of another session."""

    cost: float
    status: str = "completed"
    components: Mapping[str, float] | None = None


class ParamsHashCache:
    """In-memory cache mapping params_hash to evaluated cost.

    Thin wrapper; persistence is handled by the DuckDB ``calibration_iterations``
    table (column ``params_hash``). This class is for the current run only.
    """

    def __init__(self) -> None:
        self._hits: dict[str, CachedEvaluation] = {}

    def __contains__(self, key: str) -> bool:
        return key in self._hits

    def get(self, key: str) -> CachedEvaluation | None:
        return self._hits.get(key)

    def put(
        self,
        key: str,
        *,
        cost: float,
        status: str = "completed",
        components: Mapping[str, float] | None = None,
    ) -> None:
        self._hits[key] = CachedEvaluation(
            cost=float(cost),
            status=status,
            components=components,
        )

    def __len__(self) -> int:
        return len(self._hits)


__all__ = [
    "CachedEvaluation",
    "ParamsHashCache",
    "canonical_json",
    "context_fingerprints",
    "differing_members",
    "params_hash",
]
