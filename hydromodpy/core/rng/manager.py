"""Centralized RNG seed manager.

What
----
``RngManager`` derives deterministic per-consumer child seeds from a
single ``master_seed``. Every code path that needs a random source
(stochastic calibration, mesh point sampling, synthetic forcing, ...)
goes through this manager so that the same ``master_seed`` reproduces
the same draws.

Why
---
Without a single entry point, each consumer instantiates its own
``np.random.default_rng(seed)`` from a config field that is not
persisted in the catalog. A run is then unreproducible from the snapshot.
The manager solves both problems: it is the only place where seeds are
derived, and the master seed is persisted in
``runs_environment.rng_seed`` at registration time.
"""

from __future__ import annotations

import hashlib

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

_INT64_MASK = 0x7FFFFFFFFFFFFFFF


class RngManager(BaseModel):
    """Derive child seeds and ``np.random`` generators from a master seed."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    master_seed: int = Field(
        ge=0,
        description=(
            "Master seed used to derive sub-seeds for each labeled consumer. "
            "Persisted in ``runs_environment.rng_seed`` at simulation "
            "registration time so a run can be re-executed deterministically."
        ),
    )

    def child_seed(self, label: str) -> int:
        """Derive a deterministic child seed from ``master_seed`` and ``label``."""
        if not label:
            raise ValueError("child_seed label must be a non-empty string")
        key = f"{self.master_seed}::{label}".encode()
        digest = hashlib.blake2b(key, digest_size=8).digest()
        return int.from_bytes(digest, "big") & _INT64_MASK

    def child_rng(self, label: str) -> np.random.Generator:
        """Return a ``numpy`` ``Generator`` seeded from ``child_seed(label)``."""
        return np.random.default_rng(self.child_seed(label))
