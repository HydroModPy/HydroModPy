"""The ``values/1`` rule: one digest for a block of values, whatever their dtype.

A seal compares the values of two runs, not their files. The bytes of a Zarr
chunk change when its codec changes, and a field written in float32 says less
than the same field in float64, so the rule works on values: every number is
compared as float64, negative zero reads as zero, every NaN reads as the same
NaN, a boolean reads as 0 or 1, an integer below 2^53 reads as its float64 and
a larger integer as its exact decimal bytes, a text as its canonical JSON. The
shape and the order of the values enter the digest, so two fields of the same
numbers in different shapes never read equal.

The rule is written once: :func:`value_digest` for a block,
:class:`ValueDigester` for a field written one timestep at a time.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any, Final

import numpy as np

from hydromodpy.core.io.canonical_json import dumps as canonical_dumps

VALUES_RULE: Final[str] = "values/1"
"""Name of the rule, written in the seal beside the digests it produced."""

_FLOAT64_MAX_INT: Final[int] = 1 << 53
"""Below this bound every integer is exactly a float64."""

_CANONICAL_NAN: Final[np.float64] = np.float64("nan")
"""The one NaN the rule hashes, whatever payload the value it was read from carried."""

_FLOAT_KIND: Final[bytes] = b"array/float64\0"
_INTEGER_KIND: Final[bytes] = b"array/integer\0"
_JSON_KIND: Final[bytes] = b"array/json\0"
_SCALAR_INTEGER_KIND: Final[bytes] = b"integer\0"
_JSON_SCALAR_KIND: Final[bytes] = b"json\0"


def value_digest(values: Any) -> str:
    """Return the ``values/1`` digest of one block of values.

    ``values`` is a NumPy array, a NumPy or Python scalar, a list, a mapping or
    a string. Anything else is refused: a value the rule cannot read must not
    be sealed as if it had one.
    """
    digest = hashlib.sha256()
    digest.update(VALUES_RULE.encode("utf-8"))
    digest.update(b"\0")
    digest.update(_payload(values))
    return digest.hexdigest()


class ValueDigester:
    """The digest of a field written one timestep at a time.

    ``update`` takes the values of one step, in any order. ``digest`` folds
    them in the order of the steps, so a writer may stream a transient field
    and still produce the digest the reader recomputes from the store.
    """

    def __init__(self) -> None:
        self._steps: dict[int, str] = {}

    def update(self, step: int, values: Any) -> None:
        """Record the values of *step*."""
        self._steps[int(step)] = value_digest(values)

    def digest(self, n_steps: int) -> str:
        """Return the digest of the field, every step from 0 to *n_steps* - 1 folded in order."""
        return fold_steps(self._steps, n_steps)


def fold_steps(digests: Mapping[int, str], n_steps: int) -> str:
    """Fold per-step digests into the digest of the whole field, in step order.

    A step with no digest is refused by name: a field that misses a step is not
    a field, and the seal must not pretend it is.
    """
    count = int(n_steps)
    missing = [step for step in range(count) if step not in digests]
    if missing:
        shown = ", ".join(str(step) for step in missing[:5])
        more = "" if len(missing) <= 5 else f" and {len(missing) - 5} more"
        raise ValueError(f"no digest for step(s) {shown}{more} of {count}")
    body = canonical_dumps({"rule": VALUES_RULE, "steps": [digests[step] for step in range(count)]})
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _payload(values: Any) -> bytes:
    if isinstance(values, np.ndarray):
        return _array_payload(values)
    if isinstance(values, np.generic):
        return _payload(np.asarray(values))
    if isinstance(values, bool):
        return _array_payload(np.asarray(values))
    if isinstance(values, int):
        if abs(values) < _FLOAT64_MAX_INT:
            return _array_payload(np.asarray(float(values)))
        return _SCALAR_INTEGER_KIND + str(int(values)).encode("ascii")
    if isinstance(values, float):
        return _array_payload(np.asarray(values, dtype=np.float64))
    if isinstance(values, str | bytes):
        return _JSON_SCALAR_KIND + canonical_dumps(_text(values)).encode("utf-8")
    if isinstance(values, Mapping):
        return _JSON_SCALAR_KIND + canonical_dumps(_jsonable(values)).encode("utf-8")
    if isinstance(values, list | tuple):
        return _JSON_SCALAR_KIND + canonical_dumps(_jsonable(values)).encode("utf-8")
    if values is None:
        return _JSON_SCALAR_KIND + canonical_dumps(None).encode("utf-8")
    raise TypeError(f"values/1 cannot digest a {type(values).__name__}")


def _array_payload(values: np.ndarray) -> bytes:
    array = np.asarray(values)
    kind = array.dtype.kind
    if kind in "biuf":
        return _numeric_payload(array)
    return (
        _JSON_KIND
        + _shape(array.shape)
        + canonical_dumps(_jsonable(array.tolist())).encode("utf-8")
    )


def _numeric_payload(array: np.ndarray) -> bytes:
    if array.dtype.kind in "iu" and not _fits_float64(array):
        numbers = ",".join(str(int(value)) for value in array.ravel())
        return (
            _INTEGER_KIND
            + array.dtype.name.encode("ascii")
            + b"\0"
            + _shape(array.shape)
            + numbers.encode("ascii")
        )
    data = np.asarray(array, dtype="<f8") + 0.0
    nan = np.isnan(data)
    if nan.any():
        data = np.where(nan, _CANONICAL_NAN, data)
    return _FLOAT_KIND + _shape(array.shape) + data.tobytes()


def _fits_float64(array: np.ndarray) -> bool:
    largest = np.abs(np.asarray(array, dtype=np.float64))
    return bool(largest.size == 0 or largest.max() < _FLOAT64_MAX_INT)


def _shape(shape: tuple[int, ...]) -> bytes:
    return np.asarray(shape, dtype="<i8").tobytes()


def _text(value: str | bytes) -> str:
    return value if isinstance(value, str) else value.decode("utf-8", "surrogateescape")


def _jsonable(value: Any) -> Any:
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return _jsonable(value.tolist())
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(item) for item in value]
    return value


__all__ = ["VALUES_RULE", "ValueDigester", "fold_steps", "value_digest"]
