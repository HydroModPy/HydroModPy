"""The compact storage precision: float32 with the mantissa rounded to nearest at 16 bits.

Every stored field of a compact run goes through ``round_mantissa``. The tests pin the
relative error bound and the values where a bit trick goes wrong (zeros, subnormals,
the edge of the float32 range).
"""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.core.fields.precision import (
    KEPT_MANTISSA_BITS,
    MAX_RELATIVE_ERROR,
    round_mantissa,
    to_storage_precision,
)

DROPPED_BITS = 23 - KEPT_MANTISSA_BITS
DROPPED_MASK = np.uint32((1 << DROPPED_BITS) - 1)
FLOAT32_MAX = float(np.finfo(np.float32).max)


@pytest.fixture
def spread() -> np.ndarray:
    rng = np.random.default_rng(20260929)
    magnitude = 10.0 ** rng.uniform(-30.0, 30.0, 200_000)
    return magnitude * rng.choice([-1.0, 1.0], magnitude.size)


def test_relative_error_bound(spread) -> None:
    rounded = round_mantissa(spread).astype(np.float64)

    relative = np.abs(rounded - spread) / np.abs(spread)
    assert relative.max() <= MAX_RELATIVE_ERROR
    assert MAX_RELATIVE_ERROR == pytest.approx(7.63e-6, rel=1e-3)


def test_zeros_keep_their_sign() -> None:
    rounded = round_mantissa(np.array([0.0, -0.0]))

    np.testing.assert_array_equal(rounded, [0.0, 0.0])
    np.testing.assert_array_equal(np.signbit(rounded), [False, True])


def test_subnormals() -> None:
    tiny = np.array([1e-40, -1e-40, 3e-44], dtype=np.float64)

    rounded = round_mantissa(tiny)

    assert np.isfinite(rounded).all()
    assert np.all(rounded != 0.0)
    np.testing.assert_array_equal(np.sign(rounded), np.sign(tiny))
    # The float32 subnormal grid is 2**-149; the error is at most one step of it.
    assert np.abs(rounded.astype(np.float64) - tiny).max() <= 2.0**-149


def test_float32_edge_stays_finite() -> None:
    edge = np.array([FLOAT32_MAX, -FLOAT32_MAX, np.nextafter(FLOAT32_MAX, 0.0)])

    rounded = round_mantissa(edge)

    assert np.isfinite(rounded).all()
    np.testing.assert_array_equal(np.sign(rounded), np.sign(edge))
    assert not np.any(rounded.view(np.uint32) & DROPPED_MASK)
    assert np.abs(rounded.astype(np.float64) - edge).max() / FLOAT32_MAX <= 2.0 ** (
        -KEPT_MANTISSA_BITS
    )


def test_value_beyond_float32_refused() -> None:
    with pytest.raises(ValueError, match="float32 range"):
        round_mantissa(np.array([1.0, 1e39]))


def test_kept_bits_refused() -> None:
    with pytest.raises(ValueError, match="kept_bits"):
        round_mantissa([1.0], kept_bits=0)
    with pytest.raises(ValueError, match="kept_bits"):
        round_mantissa([1.0], kept_bits=24)


def test_storage_precision() -> None:
    floats = np.array([[130.123456789, -1.23456789e-3]])
    integers = np.array([[0, 1, 2]], dtype=np.int32)
    flags = np.array([[True, False]])

    assert to_storage_precision(floats, "compact").dtype == np.float32
    assert to_storage_precision(floats, "exact") is floats
    assert to_storage_precision(integers, "compact") is integers
    assert to_storage_precision(flags, "compact") is flags
    with pytest.raises(ValueError, match="field precision"):
        to_storage_precision(floats, "float16")  # type: ignore[arg-type]
