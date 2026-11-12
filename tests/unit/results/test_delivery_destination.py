"""Where a delivery goes: the syntax of ``deliver_to``, its refusals, and an address."""

from __future__ import annotations

import re

import pytest

from hydromodpy.results.exporters.destination import parse_destination

ACCEPTED = [
    pytest.param("/srv/depot/", "path", None, None, "/srv/depot/", True, id="posix folder"),
    pytest.param(
        "/srv/depot/head.tif", "path", None, None, "/srv/depot/head.tif", False, id="posix file"
    ),
    pytest.param(
        "C:\\Users\\bb\\depot\\",
        "path",
        None,
        None,
        "C:\\Users\\bb\\depot\\",
        True,
        id="windows folder",
    ),
    pytest.param(
        "C:/Users/bb/depot/head.tif",
        "path",
        None,
        None,
        "C:/Users/bb/depot/head.tif",
        False,
        id="windows file with forward slashes",
    ),
    pytest.param(
        "\\\\serveur\\partage\\depot\\",
        "path",
        None,
        None,
        "\\\\serveur\\partage\\depot\\",
        True,
        id="unc folder",
    ),
    pytest.param(
        "ftp://data.example.org/depot/",
        "ftp",
        "data.example.org",
        None,
        "/depot/",
        True,
        id="ftp folder",
    ),
    pytest.param(
        "ftp://data.example.org:2121/depot/head.tif",
        "ftp",
        "data.example.org",
        2121,
        "/depot/head.tif",
        False,
        id="ftp file with port",
    ),
    pytest.param(
        "ftps://data.example.org/depot/",
        "ftps",
        "data.example.org",
        None,
        "/depot/",
        True,
        id="ftps folder",
    ),
    pytest.param(
        "sftp://data.example.org/depot/head.tif",
        "sftp",
        "data.example.org",
        None,
        "/depot/head.tif",
        False,
        id="sftp file",
    ),
]


REFUSED = [
    pytest.param(
        "livrables/nancon",
        "is a relative path",
        id="relative posix path",
    ),
    pytest.param(
        "depot\\head.tif",
        "is a relative path",
        id="relative windows path",
    ),
    pytest.param(
        "\\\\serveur",
        "is a relative path",
        id="unc without a share",
    ),
    pytest.param(
        "https://zenodo.org/deposit/1",
        "uses https://, which HydroModPy does not deliver to",
        id="other scheme",
    ),
    pytest.param(
        "s3://bucket/out/",
        "uses s3://",
        id="object store",
    ),
    pytest.param(
        "ftp://bb:secret@data.example.org/depot/",
        "carries a user or a password",
        id="identity in the address",
    ),
    pytest.param(
        "ftp://data.example.org/depot/?case=a",
        "carries a query or a fragment",
        id="query",
    ),
    pytest.param(
        "ftp://data.example.org/depot/#top",
        "carries a query or a fragment",
        id="fragment",
    ),
    pytest.param(
        "ftp:///depot/",
        "names no host",
        id="no host",
    ),
    pytest.param(
        "ftp://data.example.org:ftp/depot/",
        "names a port that is not a number",
        id="port is not a number",
    ),
]


@pytest.mark.parametrize(("text", "phrase"), REFUSED)
def test_a_refused_destination_says_what_to_write(text: str, phrase: str) -> None:
    with pytest.raises(ValueError, match=re.escape(phrase)):
        parse_destination(text)
