"""Tests for results/storage/array_fingerprint.py - fingerprinting."""

from __future__ import annotations

import numpy as np

from hydromodpy.results.storage.array_fingerprint import fingerprint


class TestFingerprint:
    def test_handles_nan(self):
        data = np.array([1.0, np.nan, 3.0])
        fp = fingerprint(data)
        assert fp["stats"]["mean"] == 2.0  # nanmean
        assert fp["stats"]["min"] == 1.0
