"""One hash of a file and one of a value, both read at the seal."""

from __future__ import annotations

from hydromodpy.core.io.canonical_json import sha256_value


def test_the_digest_of_a_value_ignores_the_order_of_a_mapping():
    assert sha256_value({"b": 1, "a": 2}) == sha256_value({"a": 2, "b": 1})
    assert sha256_value({"a": 2}) != sha256_value({"a": 3})
