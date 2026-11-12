"""``fingerprint`` summarises an array by its statistics and a checksum."""

from __future__ import annotations

import numpy as np

from hydromodpy.results.storage.array_fingerprint import fingerprint


def test_fingerprint_ignores_nan_in_statistics():
    data = np.array([1.0, np.nan, 3.0])

    stats = fingerprint(data)["stats"]

    assert stats["mean"] == 2.0  # nanmean
    assert stats["min"] == 1.0
