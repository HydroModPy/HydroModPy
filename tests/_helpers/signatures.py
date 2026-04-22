"""Compact signatures for field comparison across tiers.

A :class:`FieldSignature` captures 12 summary statistics of a numeric
field plus shape and dtype. It is deterministic, JSON-serializable and
cross-platform: two signatures agree iff the two underlying arrays
agree to the reported tolerance on every reduction.

Signatures are stable under permutation of elements *except* for the
``moment_1`` term, which is sensitive to spatial reordering and detects
silent indexing regressions.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np


@dataclass(frozen=True)
class FieldSignature:
    """Twelve-field statistical signature of a numeric array."""

    count: int
    min: float
    max: float
    p05: float
    p25: float
    p50: float
    p75: float
    p95: float
    mean: float
    std: float
    sum: float
    moment_1: float
    shape: tuple[int, ...]
    dtype: str

    @classmethod
    def from_array(cls, arr: np.ndarray) -> "FieldSignature":
        """Build a signature from a numeric array, ignoring non-finite entries."""
        arr = np.asarray(arr)
        finite = arr[np.isfinite(arr)] if arr.size else arr
        if finite.size == 0:
            nan = float("nan")
            return cls(
                count=0,
                min=nan,
                max=nan,
                p05=nan,
                p25=nan,
                p50=nan,
                p75=nan,
                p95=nan,
                mean=nan,
                std=nan,
                sum=nan,
                moment_1=nan,
                shape=tuple(arr.shape),
                dtype=str(arr.dtype),
            )
        q = np.quantile(finite, [0.05, 0.25, 0.50, 0.75, 0.95])
        return cls(
            count=int(finite.size),
            min=float(finite.min()),
            max=float(finite.max()),
            p05=float(q[0]),
            p25=float(q[1]),
            p50=float(q[2]),
            p75=float(q[3]),
            p95=float(q[4]),
            mean=float(finite.mean()),
            std=float(finite.std(ddof=0)),
            sum=float(finite.sum()),
            moment_1=float(np.sum(finite.astype(float) * np.arange(finite.size, dtype=float))),
            shape=tuple(arr.shape),
            dtype=str(arr.dtype),
        )

    def to_dict(self) -> dict:
        """Return a plain-dict representation with JSON-safe types."""
        payload = asdict(self)
        payload["shape"] = list(self.shape)
        return payload
