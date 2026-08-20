"""Unit tests for input array fingerprinting (empty guard + reshape detection)."""

from __future__ import annotations

import numpy as np

from hydromodpy.results.storage.array_fingerprint import fingerprint, verify_fingerprint


def test_fingerprint_handles_empty_array_without_raising():
    fp = fingerprint(np.array([], dtype="float64"))
    # nanmin/nanmax would raise on a zero-size array; stats are None instead.
    assert fp["stats"] is None
    assert fp["shape"] == [0]
    assert fp["checksum"]


def test_verify_detects_reshape_with_identical_bytes():
    flat = np.arange(6, dtype="float64")
    fp = fingerprint(flat)
    # Same bytes, different shape: the bytes-only checksum matches but shape does not.
    reshaped = flat.reshape(2, 3)
    assert verify_fingerprint(fp, reshaped) is False
    assert verify_fingerprint(fp, flat) is True


def test_verify_detects_dtype_change_with_same_bytes():
    data = np.array([1, 2, 3, 4], dtype="int32")
    fp = fingerprint(data)
    viewed = data.view("float32")  # identical bytes, different dtype and meaning
    assert verify_fingerprint(fp, viewed) is False
