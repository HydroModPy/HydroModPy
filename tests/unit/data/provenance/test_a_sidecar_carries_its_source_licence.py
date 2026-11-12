"""A fetched file's sidecar states the licence of its source.

The licence comes from the source registry, a licence given by the caller (a
``url`` source that declares one) wins, and a licence already determined for
the same bytes survives a rewrite.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.core.exceptions import DataCacheError
from hydromodpy.data.provenance import sidecars
from hydromodpy.data.provenance.sidecars import (
    CacheIndex,
    Sidecar,
    compute_sha256,
    load_sidecar,
    sidecar_path_for,
    write_sidecar,
)


def _raw(tmp_path: Path) -> Path:
    path = tmp_path / "data" / "geology" / "geology.gpkg"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"geology")
    return path


def _record(path: Path, source: str, **fields: object) -> Sidecar:
    CacheIndex(path.parents[1]).record(path, variable="geology", source=source, **fields)
    return load_sidecar(path)


def _declare(path: Path, licence: str, sha256: str | None = None) -> None:
    write_sidecar(
        path,
        Sidecar(
            source="brgm_1m",
            variable="geology",
            sha256=sha256 or compute_sha256(path),
            bytes=path.stat().st_size,
            license=licence,
        ),
    )


def test_a_given_licence_wins(tmp_path: Path) -> None:
    assert _record(_raw(tmp_path), "url", license="CC-BY-4.0").license == "CC-BY-4.0"


def test_a_sidecar_that_cannot_be_written_fails_the_record_and_leaves_no_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The sidecar is the row: a record whose sidecar is not written is no record.
    def refuse(*args: object, **kwargs: object) -> None:
        raise OSError("read-only folder")

    path = _raw(tmp_path)
    index = CacheIndex(tmp_path / "data")
    monkeypatch.setattr(sidecars, "write_sidecar", refuse)
    with pytest.raises(OSError, match="read-only"):
        index.record(path, variable="geology", source="brgm_1m")
    assert index.rows() == []
    assert not sidecar_path_for(path).exists()


def test_a_user_file_is_no_row_of_the_cache(tmp_path: Path) -> None:
    with pytest.raises(DataCacheError, match="user file"):
        _record(_raw(tmp_path), "file")
