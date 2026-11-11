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


def test_a_reshape_with_identical_bytes_changes_the_shape_and_keeps_the_checksum():
    flat = np.arange(6, dtype="float64")
    reshaped = flat.reshape(2, 3)
    # The checksum hashes the bytes only: the shape field tells the two apart.
    assert fingerprint(reshaped)["checksum"] == fingerprint(flat)["checksum"]
    assert fingerprint(reshaped)["shape"] != fingerprint(flat)["shape"]


def test_a_dtype_view_with_identical_bytes_changes_the_dtype_and_keeps_the_checksum():
    data = np.array([1, 2, 3, 4], dtype="int32")
    viewed = data.view("float32")  # identical bytes, different dtype and meaning
    assert fingerprint(viewed)["checksum"] == fingerprint(data)["checksum"]
    assert fingerprint(viewed)["dtype"] != fingerprint(data)["dtype"]
