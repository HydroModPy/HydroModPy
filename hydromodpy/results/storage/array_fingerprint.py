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
    # nanmin/nanmax/nanmean raise on a zero-size array; a legitimately empty
    # forcing array must not abort provenance recording.
    stats = None
    if data.size > 0:
        stats = {
            "mean": float(np.nanmean(data)),
            "min": float(np.nanmin(data)),
            "max": float(np.nanmax(data)),
            "std": float(np.nanstd(data)),
        }
    return {
        "checksum": hashlib.sha256(contiguous.tobytes()).hexdigest(),
        "shape": list(data.shape),
        "dtype": str(data.dtype),
        "stats": stats,
    }
