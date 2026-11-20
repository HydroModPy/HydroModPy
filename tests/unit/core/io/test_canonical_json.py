"""The digest of a value read at the seal does not depend on the order of a mapping."""

from __future__ import annotations

from hydromodpy.core.io.canonical_json import sha256_value


def test_digest_ignores_mapping_order():
    assert sha256_value({"b": 1, "a": 2}) == sha256_value({"a": 2, "b": 1})
    assert sha256_value({"a": 2}) != sha256_value({"a": 3})
