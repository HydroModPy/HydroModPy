"""Tests for simulation/results/provenance.py — fingerprinting."""

from __future__ import annotations

import numpy as np

from hydromodpy.simulation.results.provenance import fingerprint, verify_fingerprint


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


class TestVerifyFingerprint:
    def test_match(self):
        data = np.random.default_rng(7).random(200)
        fp = fingerprint(data)
        assert verify_fingerprint(fp, data)

    def test_mismatch(self):
        data = np.random.default_rng(7).random(200)
        fp = fingerprint(data)
        altered = data.copy()
        altered[0] += 1e-10
        assert not verify_fingerprint(fp, altered)

    def test_non_contiguous_verify(self):
        data = np.arange(20, dtype="float64").reshape(4, 5)
        fp = fingerprint(data)
        view = np.ascontiguousarray(data)
        assert verify_fingerprint(fp, view)
