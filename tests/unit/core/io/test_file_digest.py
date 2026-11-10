"""One hash of a file and one of a value, both read at the seal."""

from __future__ import annotations

import hashlib

from hydromodpy.core.io.canonical_json import sha256_value
from hydromodpy.core.io.file_digest import CHUNK_BYTES, sha256_and_size, sha256_of


def test_the_digest_and_the_size_of_a_file_are_the_bytes(tmp_path):
    path = tmp_path / "inputs.json"
    body = b'{"a": 1}\n'
    path.write_bytes(body)

    assert sha256_and_size(path) == (hashlib.sha256(body).hexdigest(), len(body))
    assert sha256_of(path) == sha256_and_size(path)[0]


def test_a_file_over_one_chunk_hashes_the_same(tmp_path):
    path = tmp_path / "fields.bin"
    body = bytes(range(256)) * (CHUNK_BYTES // 256 + 2)
    path.write_bytes(body)

    assert sha256_and_size(path) == (hashlib.sha256(body).hexdigest(), len(body))


def test_two_empty_files_hash_the_same(tmp_path):
    first = tmp_path / "a"
    second = tmp_path / "b"
    first.write_bytes(b"")
    second.write_bytes(b"")

    assert sha256_and_size(first) == (hashlib.sha256(b"").hexdigest(), 0)
    assert sha256_of(first) == sha256_of(second)


def test_the_digest_of_a_value_ignores_the_order_of_a_mapping():
    assert sha256_value({"b": 1, "a": 2}) == sha256_value({"a": 2, "b": 1})
    assert sha256_value({"a": 2}) != sha256_value({"a": 3})
