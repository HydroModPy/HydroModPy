"""Storage precision of time-varying field arrays.

A field kept in the compact form is float32 whose mantissa is rounded to
nearest, ties to even, at ``KEPT_MANTISSA_BITS`` explicit bits. The dropped
low bits are zeros, which the bitshuffle filter of the field codec packs
away. This is the ``bitround`` quantization of CF-1.11, section 8.4.

Each value moves by at most half a unit in its last kept bit, so the relative
error of a normal value is at most ``MAX_RELATIVE_ERROR`` (2**-17, about
7.6e-6). A 130 m head moves by 1 mm at most. The rounding is done once, from
float64, so the float32 cast that follows is exact.
"""

from __future__ import annotations

from typing import Literal

import numpy as np
from numpy.typing import ArrayLike

FieldPrecision = Literal["compact", "exact"]
"""``compact`` rounds float fields to float32, ``exact`` keeps them as written."""

DEFAULT_FIELD_PRECISION: FieldPrecision = "compact"

KEPT_MANTISSA_BITS = 16
"""Explicit mantissa bits a compact value keeps, out of the 23 of a float32."""

MAX_RELATIVE_ERROR = 2.0 ** -(KEPT_MANTISSA_BITS + 1)
"""Bound on ``|rounded - value| / |value|`` for a normal float32 value."""

QUANTIZATION_ALGORITHM = "bitround"
"""CF-1.11 name of the quantization this module applies."""

_FLOAT64_MANTISSA_BITS = 52
_FLOAT32_MANTISSA_BITS = 23
_FLOAT32_MAX = float(np.finfo(np.float32).max)


def round_mantissa(values: ArrayLike, kept_bits: int = KEPT_MANTISSA_BITS) -> np.ndarray:
    """Return ``values`` as float32 rounded to nearest at ``kept_bits`` mantissa bits.

    NaN stays NaN, infinities stay infinite, zeros keep their sign. A finite
    value never becomes infinite: the few values next to the float32 maximum
    that would round up past it are cut down to the largest kept value instead.

    Raises
    ------
    ValueError
        ``kept_bits`` is outside 1..23, or a finite value lies beyond the
        float32 range and cannot be stored in it at all.
    """
    if not 1 <= int(kept_bits) <= _FLOAT32_MANTISSA_BITS:
        raise ValueError(f"kept_bits must lie in 1..{_FLOAT32_MANTISSA_BITS}, got {kept_bits}.")
    source = np.array(values, dtype=np.float64)
    nan = np.isnan(source)
    finite = np.isfinite(source)
    beyond = finite & ((source > _FLOAT32_MAX) | (source < -_FLOAT32_MAX))
    if beyond.any():
        raise ValueError(
            f"{int(beyond.sum())} finite value(s) exceed the float32 range "
            f"(|x| > {_FLOAT32_MAX:.3e}) and cannot be stored as float32."
        )

    drop = _FLOAT64_MANTISSA_BITS - int(kept_bits)
    bits = source.view(np.uint64)
    lowest_kept = np.right_shift(bits, np.uint64(drop))
    np.bitwise_and(lowest_kept, np.uint64(1), out=lowest_kept)
    bits += np.uint64((1 << (drop - 1)) - 1)
    bits += lowest_kept
    del lowest_kept
    np.bitwise_and(bits, np.uint64(~((1 << drop) - 1) & 0xFFFF_FFFF_FFFF_FFFF), out=bits)

    with np.errstate(over="ignore"):
        rounded = source.astype(np.float32)
    overflow = finite & np.isinf(rounded)
    if overflow.any():
        largest_kept = np.float32((2.0 - 2.0 ** -int(kept_bits)) * 2.0**127)
        rounded[overflow] = np.copysign(largest_kept, source[overflow])
    rounded[nan] = np.float32(np.nan)
    return rounded


def to_storage_precision(values: ArrayLike, precision: FieldPrecision) -> np.ndarray:
    """Return a field array in the precision a store keeps.

    Only floating arrays change, and only under ``compact``. Integer and
    boolean arrays, and every array under ``exact``, come back as given.
    """
    if precision not in ("compact", "exact"):
        raise ValueError(f"Unknown field precision {precision!r}: expected 'compact' or 'exact'.")
    array = np.asarray(values)
    if precision == "exact" or not np.issubdtype(array.dtype, np.floating):
        return array
    return round_mantissa(array)


__all__ = [
    "DEFAULT_FIELD_PRECISION",
    "KEPT_MANTISSA_BITS",
    "MAX_RELATIVE_ERROR",
    "QUANTIZATION_ALGORITHM",
    "FieldPrecision",
    "round_mantissa",
    "to_storage_precision",
]
