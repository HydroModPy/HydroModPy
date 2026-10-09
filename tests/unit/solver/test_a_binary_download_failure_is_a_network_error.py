"""A solver binary that cannot be fetched raises a typed network error.

urllib's URLError used to reach the user as is: exit 1 from ``hmp
install-binaries`` and a bare ``URLError`` in the ``run_solver`` step of a run.
"""

from __future__ import annotations

import urllib.error
from pathlib import Path

import pytest

from hydromodpy.cli.helpers import EXIT_VALIDATION, exit_code_for
from hydromodpy.core.exceptions import NetworkError
from hydromodpy.solver.modflow_common import binaries


def _failing(exc: BaseException):
    def get_modflow(*_args, **_kwargs):
        raise exc

    return get_modflow


@pytest.mark.parametrize(
    "raised",
    [
        urllib.error.URLError(ConnectionRefusedError(111, "Connection refused")),
        RuntimeError("cannot retrieve data from https://api.github.com/x"),
        ValueError("use GITHUB_TOKEN env to bypass rate limit (HTTP Error 403)"),
    ],
)
def test_a_network_failure_names_the_address_and_what_to_set(
    monkeypatch, tmp_path: Path, raised: BaseException
) -> None:
    if isinstance(raised, RuntimeError):
        raised.__cause__ = urllib.error.HTTPError("https://api.github.com/x", 503, "down", {}, None)
    monkeypatch.setattr("flopy.utils.get_modflow", _failing(raised))

    with pytest.raises(NetworkError) as caught:
        binaries.download_solver_binaries(tmp_path, subset=["mf6"], release="23.0")

    message = str(caught.value)
    assert binaries.release_url("23.0") in message
    assert "HTTPS_PROXY" in message
    assert "GITHUB_TOKEN" in message
    assert exit_code_for(caught.value) == EXIT_VALIDATION == 16


def test_another_failure_is_left_as_it_is(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("flopy.utils.get_modflow", _failing(ValueError("Release 99 not found")))

    with pytest.raises(ValueError, match="Release 99 not found"):
        binaries.download_solver_binaries(tmp_path, subset=["mf6"], release="99")


def test_the_latest_release_has_its_own_address() -> None:
    assert binaries.release_url("latest").endswith("/releases/latest")
