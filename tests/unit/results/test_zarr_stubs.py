"""Unit tests for the optional fsspec Zarr store stub."""

from __future__ import annotations

import pytest

from hydromodpy.results.zarr_store import FsspecZarrStore


def test_fsspec_zarr_store_raises_not_implemented() -> None:
    store = FsspecZarrStore("s3://bucket/path", anon=True)
    assert store.uri == "s3://bucket/path"
    assert store.storage_options == {"anon": True}
    with pytest.raises(NotImplementedError, match=r"hydromodpy\[cloud\]"):
        store.open()


def test_fsspec_zarr_store_close_is_noop() -> None:
    FsspecZarrStore("gs://x/y").close()
