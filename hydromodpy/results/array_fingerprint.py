"""Input provenance fingerprinting for simulation reproducibility."""

from __future__ import annotations

import hashlib

import numpy as np


def fingerprint(data: np.ndarray) -> dict:
    """Compute a lightweight fingerprint of a numpy array.

    Returns a dict with a SHA-256 checksum, array metadata, and summary
    statistics. Intended for provenance tracking of forcing data injected
    into the solver.

    Parameters
    ----------
    data : np.ndarray
        Array to fingerprint (any shape).

    Returns
    -------
    dict
        Keys: ``checksum``, ``shape``, ``dtype``, ``stats``
        (with ``mean``, ``min``, ``max``, ``std``).
    """
    contiguous = np.ascontiguousarray(data)
    return {
        "checksum": hashlib.sha256(contiguous.tobytes()).hexdigest(),
        "shape": list(data.shape),
        "dtype": str(data.dtype),
        "stats": {
            "mean": float(np.nanmean(data)),
            "min": float(np.nanmin(data)),
            "max": float(np.nanmax(data)),
            "std": float(np.nanstd(data)),
        },
    }


def verify_fingerprint(stored: dict, current: np.ndarray) -> bool:
    """Check whether *current* matches a previously stored fingerprint.

    Parameters
    ----------
    stored : dict
        Fingerprint dict as returned by :func:`fingerprint`.
    current : np.ndarray
        Array to compare against the stored fingerprint.

    Returns
    -------
    bool
        ``True`` if the SHA-256 checksums match.
    """
    contiguous = np.ascontiguousarray(current)
    current_hash = hashlib.sha256(contiguous.tobytes()).hexdigest()
    return current_hash == stored["checksum"]
