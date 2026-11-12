"""Unit tests for input array fingerprinting (empty guard + reshape detection)."""

from __future__ import annotations

import numpy as np

from hydromodpy.results.storage.array_fingerprint import fingerprint


def test_fingerprint_handles_empty_array_without_raising():
    fp = fingerprint(np.array([], dtype="float64"))
    # nanmin/nanmax would raise on a zero-size array; stats are None instead.
    assert fp["stats"] is None
    assert fp["shape"] == [0]
    assert fp["checksum"]
