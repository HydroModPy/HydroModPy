"""The compact storage precision: float32, mantissa rounded to nearest at 16 bits.

Every stored field of a compact run goes through ``round_mantissa``. These
tests pin what it promises: the bit pattern, the error bound, and the values
where a bit trick most easily goes wrong (NaN, zeros, negatives, subnormals,
the edge of the float32 range).
"""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.core.field_precision import (
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
    """Normal values of both signs over sixty decades."""
    rng = np.random.default_rng(20260929)
    magnitude = 10.0 ** rng.uniform(-30.0, 30.0, 200_000)
    return magnitude * rng.choice([-1.0, 1.0], magnitude.size)


def test_the_result_is_float32_with_the_dropped_bits_at_zero(spread) -> None:
    rounded = round_mantissa(spread)

    assert rounded.dtype == np.float32
    assert rounded.shape == spread.shape
    assert not np.any(rounded.view(np.uint32) & DROPPED_MASK)


def test_the_relative_error_stays_within_half_a_kept_unit(spread) -> None:
    rounded = round_mantissa(spread).astype(np.float64)

    relative = np.abs(rounded - spread) / np.abs(spread)
    assert relative.max() <= MAX_RELATIVE_ERROR
    assert MAX_RELATIVE_ERROR == pytest.approx(7.63e-6, rel=1e-3)


def test_a_head_moves_by_a_millimetre_at_most() -> None:
    heads = np.linspace(128.0, 255.999, 100_001)

    error = np.abs(round_mantissa(heads).astype(np.float64) - heads)

    assert error.max() <= 2.0**7 * 2.0 ** -(KEPT_MANTISSA_BITS + 1)
    assert error.max() < 1e-3


def test_a_value_already_on_the_grid_is_left_as_it_is() -> None:
    exact = np.array([1.0, -2.5, 0.75, 1024.0, 3.0 * 2.0**-20], dtype=np.float64)

    np.testing.assert_array_equal(round_mantissa(exact), exact.astype(np.float32))


def test_rounding_twice_changes_nothing(spread) -> None:
    once = round_mantissa(spread)

    np.testing.assert_array_equal(round_mantissa(once), once)


def test_a_tie_goes_to_the_even_neighbour() -> None:
    unit = 2.0**-KEPT_MANTISSA_BITS
    ties = np.array([1.0 + 0.5 * unit, 1.0 + 1.5 * unit], dtype=np.float64)

    np.testing.assert_array_equal(round_mantissa(ties), np.array([1.0, 1.0 + 2.0 * unit]))


def test_nan_stays_nan_whatever_its_payload() -> None:
    payloads = np.array(
        [0x7FF8000000000000, 0x7FFFFFFFFFFFFFFF, 0xFFF0000000000001], dtype=np.uint64
    ).view(np.float64)

    assert np.isnan(round_mantissa(payloads)).all()


def test_zeros_keep_their_sign() -> None:
    rounded = round_mantissa(np.array([0.0, -0.0]))

    np.testing.assert_array_equal(rounded, [0.0, 0.0])
    np.testing.assert_array_equal(np.signbit(rounded), [False, True])


def test_a_negative_value_rounds_as_the_mirror_of_its_positive(spread) -> None:
    np.testing.assert_array_equal(round_mantissa(-spread), -round_mantissa(spread))


def test_infinities_stay_infinite() -> None:
    np.testing.assert_array_equal(round_mantissa([np.inf, -np.inf]), [np.inf, -np.inf])


def test_a_subnormal_stays_finite_nonzero_and_signed() -> None:
    tiny = np.array([1e-40, -1e-40, 3e-44], dtype=np.float64)

    rounded = round_mantissa(tiny)

    assert np.isfinite(rounded).all()
    assert np.all(rounded != 0.0)
    np.testing.assert_array_equal(np.sign(rounded), np.sign(tiny))
    # The float32 subnormal grid is 2**-149; the error is at most one step of it.
    assert np.abs(rounded.astype(np.float64) - tiny).max() <= 2.0**-149


def test_the_largest_float32_values_never_become_infinite() -> None:
    edge = np.array([FLOAT32_MAX, -FLOAT32_MAX, np.nextafter(FLOAT32_MAX, 0.0)])

    rounded = round_mantissa(edge)

    assert np.isfinite(rounded).all()
    np.testing.assert_array_equal(np.sign(rounded), np.sign(edge))
    assert not np.any(rounded.view(np.uint32) & DROPPED_MASK)
    assert np.abs(rounded.astype(np.float64) - edge).max() / FLOAT32_MAX <= 2.0 ** (
        -KEPT_MANTISSA_BITS
    )


def test_a_large_value_inside_the_float32_range_keeps_the_bound() -> None:
    large = np.array([1e30, -3e35, 1e38])

    relative = np.abs(round_mantissa(large).astype(np.float64) - large) / np.abs(large)

    assert relative.max() <= MAX_RELATIVE_ERROR


def test_a_finite_value_beyond_float32_is_refused() -> None:
    with pytest.raises(ValueError, match="float32 range"):
        round_mantissa(np.array([1.0, 1e39]))


def test_the_kept_bits_are_checked() -> None:
    with pytest.raises(ValueError, match="kept_bits"):
        round_mantissa([1.0], kept_bits=0)
    with pytest.raises(ValueError, match="kept_bits"):
        round_mantissa([1.0], kept_bits=24)


def test_a_float32_input_is_rounded_the_same_way() -> None:
    values = np.array([130.123456, -0.0012345, 7.5e-9], dtype=np.float32)

    np.testing.assert_array_equal(round_mantissa(values), round_mantissa(values.astype(np.float64)))


def test_the_storage_precision_rounds_floats_only_under_compact() -> None:
    floats = np.array([[130.123456789, -1.23456789e-3]])
    integers = np.array([[0, 1, 2]], dtype=np.int32)
    flags = np.array([[True, False]])

    assert to_storage_precision(floats, "compact").dtype == np.float32
    assert to_storage_precision(floats, "exact") is floats
    assert to_storage_precision(integers, "compact") is integers
    assert to_storage_precision(flags, "compact") is flags
    with pytest.raises(ValueError, match="field precision"):
        to_storage_precision(floats, "float16")  # type: ignore[arg-type]
