"""Tests for results/storage/array_fingerprint.py - fingerprinting."""

from __future__ import annotations

import numpy as np

from hydromodpy.results.storage.array_fingerprint import fingerprint


class TestFingerprint:
    def test_basic(self):
        data = np.arange(100, dtype="float64")
        fp = fingerprint(data)
        assert "checksum" in fp
        assert len(fp["checksum"]) == 64  # SHA-256 hex
        assert fp["shape"] == [100]
        assert fp["dtype"] == "float64"
        assert fp["stats"]["min"] == 0.0
        assert fp["stats"]["max"] == 99.0

    def test_deterministic(self):
        data = np.random.default_rng(42).random((10, 20))
        assert fingerprint(data)["checksum"] == fingerprint(data)["checksum"]

    def test_different_data_different_hash(self):
        a = np.zeros(50)
        b = np.ones(50)
        assert fingerprint(a)["checksum"] != fingerprint(b)["checksum"]

    def test_handles_nan(self):
        data = np.array([1.0, np.nan, 3.0])
        fp = fingerprint(data)
        assert fp["stats"]["mean"] == 2.0  # nanmean
        assert fp["stats"]["min"] == 1.0

    def test_non_contiguous_array(self):
        data = np.arange(20).reshape(4, 5)[:, ::2]  # non-contiguous view
        assert not data.flags["C_CONTIGUOUS"]
        fp = fingerprint(data)
        assert fp["shape"] == [4, 3]


class TestTheFingerprintFollowsTheData:
    def test_the_same_data_gives_the_same_fingerprint(self):
        data = np.random.default_rng(7).random(200)
        assert fingerprint(data.copy()) == fingerprint(data)

    def test_a_change_of_one_value_changes_the_checksum(self):
        data = np.random.default_rng(7).random(200)
        altered = data.copy()
        altered[0] += 1e-10
        assert fingerprint(altered)["checksum"] != fingerprint(data)["checksum"]

    def test_a_non_contiguous_view_and_its_copy_agree(self):
        data = np.arange(20, dtype="float64").reshape(4, 5)
        assert fingerprint(np.ascontiguousarray(data)) == fingerprint(data)
