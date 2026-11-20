"""Where an export block sends its files once the run is sealed.

A destination is a local or UNC folder or file, or an ``ftp://``, ``ftps://``
or ``sftp://`` address. The syntax lives here, in ``results``, because
``export_spec`` validates it and a published copy removes it; the pushes live
in ``project``, which reads this module. A destination is kept as written: no
directory is created, and no percent sequence is decoded.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final
from urllib.parse import urlsplit

DELIVER_TO_KEY: Final = "deliver_to"
"""The key of an ``[[export]]`` block that names where its files go."""

DELIVERY_SCHEMES: Final[tuple[str, ...]] = ("ftp", "ftps", "sftp")
"""The schemes a delivery reaches; each one has a pusher and a probe."""

LOCAL_SCHEME: Final = "path"
"""The scheme of a destination on this machine or on a mounted share."""

_WINDOWS_DRIVE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z]:[\\/]")
_UNC: Final[re.Pattern[str]] = re.compile(r"^\\\\([^\\/]+)[\\/]([^\\/]+)")


@dataclass(frozen=True)
class Destination:
    """One place an export block delivers to, as written and as read."""

    text: str
    """The destination as written in the block."""
    scheme: str
    """``"path"``, ``"ftp"``, ``"ftps"`` or ``"sftp"``."""
    host: str | None
    """Host of a remote destination; none for a path."""
    port: int | None
    """Port of a remote destination; none when the address names none."""
    path: str
    """Absolute local path, or remote POSIX path."""
    folder: bool
    """True when the destination is a folder."""


def parse_destination(text: str) -> Destination:
    """Read one ``deliver_to`` text; refuse a form no delivery reaches."""
    if "://" in text:
        return _remote(text)
    return _local(text)


def address_of(destination: Destination, relative: str) -> str:
    """Return the address a file exported at *relative* takes on *destination*.

    *relative* is the path of the file under ``exports/``, spelled with
    forward slashes. A destination that names one file takes that file.
    """
    if not destination.folder:
        return destination.text
    separator = "\\" if destination.text.endswith("\\") else "/"
    return destination.text + relative.replace("/", separator)


def without_delivery(document: Mapping[str, Any]) -> dict[str, Any]:
    """Return *document* without ``deliver_to`` in every block of its export table."""
    cleaned = dict(document)
    blocks = cleaned.get("export")
    if isinstance(blocks, list):
        cleaned["export"] = [
            {key: value for key, value in block.items() if key != DELIVER_TO_KEY}
            if isinstance(block, Mapping)
            else block
            for block in blocks
        ]
    return cleaned


def _remote(text: str) -> Destination:
    """Read an address, with a host and an optional port."""
    parts = urlsplit(text)
    scheme = parts.scheme.lower()
    if scheme not in DELIVERY_SCHEMES:
        raise ValueError(
            f"deliver_to = {text!r} uses {scheme}://, which HydroModPy does not deliver to. "
            "It delivers to a local or UNC path and to ftp://, ftps:// and sftp:// "
            "addresses; a publication on Zenodo is hmp publish."
        )
    if parts.username is not None or parts.password is not None:
        raise ValueError(
            f"deliver_to = {text!r} carries a user or a password. Write the address alone "
            "and put the identity in a [[host]] block of credentials.toml."
        )
    if parts.query or parts.fragment:
        raise ValueError(
            f"deliver_to = {text!r} carries a query or a fragment, which a delivery does "
            "not read. Remove it."
        )
    if not parts.hostname:
        raise ValueError(f"deliver_to = {text!r} names no host.")
    try:
        port = parts.port
    except ValueError:
        raise ValueError(
            f"deliver_to = {text!r} names a port that is not a number. Write the port after "
            "the host, e.g. ftp://server:2121/depot/."
        ) from None
    path = parts.path
    return Destination(
        text=text,
        scheme=scheme,
        host=parts.hostname,
        port=port,
        path=path or "/",
        folder=path.endswith("/") or not path,
    )


def _local(text: str) -> Destination:
    """Read an absolute path, of this machine, a Windows drive or a UNC share."""
    windows = bool(_WINDOWS_DRIVE.match(text) or _UNC.match(text))
    if not (windows or text.startswith("/")):
        raise ValueError(
            f"deliver_to = {text!r} is a relative path. Write an absolute folder or file, "
            "a UNC path, or an ftp://, ftps:// or sftp:// address."
        )
    return Destination(
        text=text,
        scheme=LOCAL_SCHEME,
        host=None,
        port=None,
        path=text,
        folder=text.endswith("/") or (windows and text.endswith("\\")),
    )


__all__ = [
    "DELIVERY_SCHEMES",
    "DELIVER_TO_KEY",
    "LOCAL_SCHEME",
    "Destination",
    "address_of",
    "parse_destination",
    "without_delivery",
]
