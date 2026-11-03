"""Fetch a file whose sha256 is written in the package, and refuse any other bytes.

A file HydroModPy executes or loads, a solver binary or a native extension, comes
from a release it pins, with one digest per asset. This module holds the one
check. The bytes land beside the destination and take its name only once they hash
to the pin, so no caller can reach an unverified file. A file already at the
destination is hashed too, since a process trusts nothing it did not just check.
"""

from __future__ import annotations

import os
from pathlib import Path

import requests

from hydromodpy.core.exceptions import CacheCorruptionError, NetworkError
from hydromodpy.core.io.http_client import get_default_client
from hydromodpy.core.payload.install import sha256_of


def fetch_pinned(
    url: str,
    dest: Path,
    *,
    sha256: str,
    remedy: str,
    force: bool = False,
) -> Path:
    """Return *dest* holding the bytes *sha256* names, fetching *url* when it is absent.

    *remedy* tells the user how to proceed after a refusal. ``force`` fetches again
    over a file already there, which stays in place until the new bytes pass.
    Raises :class:`CacheCorruptionError` naming both digests when the bytes differ,
    and :class:`NetworkError` when the address cannot be read.
    """
    if dest.is_file() and not force:
        cached = sha256_of(dest)
        if cached != sha256:
            dest.unlink(missing_ok=True)
            raise CacheCorruptionError(
                f"{dest} hashes to {cached}, and HydroModPy pins sha256 {sha256} for it. It was "
                f"removed: run the same command again to fetch a clean copy. {remedy}",
                source=str(dest),
                expected=sha256,
                found=cached,
            )
        return dest

    dest.parent.mkdir(parents=True, exist_ok=True)
    partial = dest.with_name(f".{dest.name}.{os.getpid()}.part")
    try:
        found = _download(url, partial)
        if found != sha256:
            raise CacheCorruptionError(
                f"{dest.name} downloaded from {url} hashes to {found}, and HydroModPy pins "
                f"sha256 {sha256} for it. Nothing was kept. {remedy}",
                source=url,
                expected=sha256,
                found=found,
            )
        partial.replace(dest)
    finally:
        partial.unlink(missing_ok=True)
    return dest


def _download(url: str, partial: Path) -> str:
    """Stream *url* into *partial* and return the sha256 of what arrived."""
    try:
        return get_default_client().stream(url, partial).sha256
    except requests.RequestException as exc:
        # The client retries the request. A connection lost in the body comes out raw.
        raise NetworkError(
            f"HTTP GET {url} stopped in the body", url=url, last_exception=str(exc)
        ) from exc


__all__ = ["fetch_pinned"]
