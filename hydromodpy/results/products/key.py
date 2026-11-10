"""The key of a product: the digest of what the step reads and of the code.

A product is keyed by what it was computed from, not by what it is, so two runs
that read the same inputs and the same code share one product. The key reads
the digest of each input, the processing parameters, the engine and the code of
the package that computes it, at the grain of the layer matrix.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from types import MappingProxyType
from typing import Any

import numpy as np

from hydromodpy.core.code_fingerprint import code_fingerprint, layers_under
from hydromodpy.core.io.canonical_json import dumps


def array_digest(values: np.ndarray) -> str:
    """Return the sha256 of one array: its dtype, shape and C-order bytes.

    NaN is read as the one quiet NaN and ``-0.0`` as ``0.0``, so two arrays
    that differ only by a NaN sign or a zero sign give the same digest. The
    dtype enters, because a codec never reduces precision.
    """
    array = np.asarray(values)
    contiguous = np.ascontiguousarray(array)
    if array.dtype.kind == "f":
        nan = np.array(np.nan, dtype=array.dtype)
        contiguous = np.where(np.isnan(contiguous), nan, contiguous)
        contiguous = contiguous + np.zeros((), dtype=array.dtype)
    digest = hashlib.sha256()
    digest.update(array.dtype.str.encode("ascii"))
    digest.update(b"\0")
    digest.update(json.dumps(list(array.shape)).encode("ascii"))
    digest.update(b"\0")
    digest.update(contiguous.tobytes(order="C"))
    return digest.hexdigest()


def product_key(
    kind: str,
    *,
    codec: str,
    package: str,
    inputs: Mapping[str, str],
    processing: Mapping[str, Any],
    engine: Mapping[str, str] = MappingProxyType({}),
) -> str:
    """Return the key of a product, the sha256 of its canonical description.

    ``inputs`` holds one digest per role, ``processing`` the parameters the step
    used, ``engine`` the engine and its library versions, and the code enters as
    the fingerprint of the layers ``package`` may read.
    """
    payload = {
        "kind": kind,
        "codec": codec,
        "inputs": dict(inputs),
        "processing": dict(processing),
        "engine": dict(engine),
        "code": code_fingerprint(layers_under(package)),
    }
    return hashlib.sha256(dumps(payload).encode("utf-8")).hexdigest()


__all__ = ["array_digest", "product_key"]
