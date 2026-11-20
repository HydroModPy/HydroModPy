"""Fingerprint of an input array: its shape, its statistics and a checksum of its bytes."""

from __future__ import annotations

import numpy as np

from hydromodpy.results.storage.array_fingerprint import fingerprint


def test_empty_array():
    fp = fingerprint(np.array([], dtype="float64"))
    # nanmin/nanmax would raise on a zero-size array; stats are None instead.
    assert fp["stats"] is None
    assert fp["shape"] == [0]
    assert fp["checksum"]
