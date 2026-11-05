"""A file HydroModPy executes passes one check: the bytes hash to the pin, or nothing lands."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
import requests

from hydromodpy.cli.helpers import EXIT_VALIDATION, exit_code_for
from hydromodpy.core.exceptions import CacheCorruptionError, NetworkError
from hydromodpy.core.io.http_client import get_default_client
from hydromodpy.core.io.pinned_download import fetch_pinned
from tests.unit.core.io._fake_release import digest_of

PAYLOAD = b"the bytes of the release"
REMEDY = "Report it."
ADDRESS = "https://releases.example/asset"


@pytest.fixture
def served(monkeypatch: pytest.MonkeyPatch) -> str:
    """Answer ``ADDRESS`` with the payload through the real client, and any other with a 404."""

    def request(_method: str, url: str, **_kwargs: object) -> MagicMock:
        response = MagicMock(status_code=200 if url == ADDRESS else 404, headers={})
        response.iter_content = lambda chunk_size: iter([PAYLOAD])
        return response

    monkeypatch.setattr(get_default_client()._session, "request", request)
    return ADDRESS


def _no_leftover(folder: Path) -> bool:
    return not list(folder.glob(".*.part"))


def test_the_pinned_bytes_land_under_the_name(served: str, tmp_path: Path) -> None:
    dest = tmp_path / "cache" / "asset"

    assert fetch_pinned(served, dest, sha256=digest_of(PAYLOAD), remedy=REMEDY) == dest

    assert dest.read_bytes() == PAYLOAD
    assert _no_leftover(dest.parent)


def test_other_bytes_are_refused_naming_both_digests_and_nothing_lands(
    served: str, tmp_path: Path
) -> None:
    dest = tmp_path / "cache" / "asset"
    pin = digest_of(b"what the release held")

    with pytest.raises(CacheCorruptionError) as refused:
        fetch_pinned(served, dest, sha256=pin, remedy=REMEDY)

    message = str(refused.value)
    assert pin in message
    assert digest_of(PAYLOAD) in message
    assert served in message
    assert REMEDY in message
    assert not dest.exists()
    assert _no_leftover(dest.parent)
    assert exit_code_for(refused.value) == EXIT_VALIDATION


def test_a_file_already_there_is_read_without_a_download(tmp_path: Path) -> None:
    dest = tmp_path / "asset"
    dest.write_bytes(PAYLOAD)

    assert fetch_pinned("http://127.0.0.1:9/none", dest, sha256=digest_of(PAYLOAD), remedy=REMEDY)


def test_a_file_already_there_that_changed_is_removed_and_refused(tmp_path: Path) -> None:
    dest = tmp_path / "asset"
    dest.write_bytes(b"changed on disk")

    with pytest.raises(CacheCorruptionError) as refused:
        fetch_pinned("http://127.0.0.1:9/none", dest, sha256=digest_of(PAYLOAD), remedy=REMEDY)

    assert digest_of(b"changed on disk") in str(refused.value)
    assert digest_of(PAYLOAD) in str(refused.value)
    assert REMEDY in str(refused.value)
    assert not dest.exists()


def test_force_keeps_the_old_file_until_the_new_bytes_pass(served: str, tmp_path: Path) -> None:
    dest = tmp_path / "asset"
    dest.write_bytes(b"the old release")

    with pytest.raises(CacheCorruptionError):
        fetch_pinned(served, dest, sha256=digest_of(b"other"), remedy=REMEDY, force=True)
    assert dest.read_bytes() == b"the old release"

    fetch_pinned(served, dest, sha256=digest_of(PAYLOAD), remedy=REMEDY, force=True)
    assert dest.read_bytes() == PAYLOAD


def test_an_address_that_does_not_answer_is_a_network_error(served: str, tmp_path: Path) -> None:
    dest = tmp_path / "asset"

    with pytest.raises(NetworkError, match="404"):
        fetch_pinned(f"{served}/absent", dest, sha256=digest_of(PAYLOAD), remedy=REMEDY)

    assert not dest.exists()
    assert _no_leftover(tmp_path)


def test_a_connection_lost_in_the_body_is_a_network_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Client:
        def stream(self, url: str, dest: Path) -> None:
            Path(dest).write_bytes(b"half of it")
            raise requests.exceptions.ChunkedEncodingError("Connection broken")

    monkeypatch.setattr("hydromodpy.core.io.pinned_download.get_default_client", Client)

    with pytest.raises(NetworkError) as caught:
        fetch_pinned("http://x/asset", tmp_path / "asset", sha256="0" * 64, remedy=REMEDY)

    assert "Connection broken" in caught.value.context["last_exception"]
    assert not (tmp_path / "asset").exists()
    assert _no_leftover(tmp_path)
