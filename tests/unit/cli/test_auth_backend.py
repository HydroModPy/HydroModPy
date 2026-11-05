"""Unit tests for ``AuthBackend``: the user lookup order and the permissive checks."""

from __future__ import annotations

import pytest

from hydromodpy.cli.auth import AuthBackend


def test_current_user_returns_string(monkeypatch: pytest.MonkeyPatch) -> None:
    """A populated env yields the override value as a plain ``str``."""
    monkeypatch.setenv("HMP_USER", "alice")
    monkeypatch.setenv("USER", "ignored")
    monkeypatch.setenv("USERNAME", "ignored")
    result = AuthBackend().current_user()
    assert isinstance(result, str)
    assert result == "alice"


def test_current_user_handles_no_login(monkeypatch: pytest.MonkeyPatch) -> None:
    """When every env source is empty, ``getpass.getuser`` is the fallback."""
    monkeypatch.delenv("HMP_USER", raising=False)
    monkeypatch.delenv("USER", raising=False)
    monkeypatch.delenv("USERNAME", raising=False)
    monkeypatch.delenv("LOGNAME", raising=False)
    monkeypatch.setattr("getpass.getuser", lambda: "fallback_user")
    result = AuthBackend().current_user()
    assert result == "fallback_user"


def test_current_user_falls_back_to_anonymous(monkeypatch: pytest.MonkeyPatch) -> None:
    """When the system has no usable identity, the literal ``anonymous`` wins."""
    monkeypatch.delenv("HMP_USER", raising=False)
    monkeypatch.delenv("USER", raising=False)
    monkeypatch.delenv("USERNAME", raising=False)
    monkeypatch.delenv("LOGNAME", raising=False)

    def _boom() -> str:
        raise OSError("no controlling terminal")

    monkeypatch.setattr("getpass.getuser", _boom)
    result = AuthBackend().current_user()
    assert result == "anonymous"


def test_current_user_reads_the_posix_user_then_the_windows_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``USER`` comes before ``USERNAME`` once ``HMP_USER`` is absent."""
    monkeypatch.delenv("HMP_USER", raising=False)
    monkeypatch.setenv("USER", "alice")
    monkeypatch.setenv("USERNAME", "bob")
    assert AuthBackend().current_user() == "alice"
    monkeypatch.delenv("USER")
    assert AuthBackend().current_user() == "bob"


def test_auth_backend_allows_read_and_write() -> None:
    """The permissive default authorizes every resource."""
    backend = AuthBackend()
    assert backend.can_read("catalog:project:naizin") is True
    assert backend.can_write("catalog:sim:abc") is True
