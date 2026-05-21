"""Unit tests for ``LocalAuthBackend.current_user`` edge cases.

Complements ``test_auth.py`` with the three contract scenarios required by
T6.B: a stable string return value, a graceful fallback when no login is
available, and the ``"anonymous"`` literal as the last resort.
"""

from __future__ import annotations

import pytest

from hydromodpy.core.auth.backends import LocalAuthBackend


def test_current_user_returns_string(monkeypatch: pytest.MonkeyPatch) -> None:
    """A populated env yields the override value as a plain ``str``."""
    monkeypatch.setenv("HMP_USER", "alice")
    monkeypatch.setenv("USER", "ignored")
    monkeypatch.setenv("USERNAME", "ignored")
    result = LocalAuthBackend().current_user()
    assert isinstance(result, str)
    assert result == "alice"


def test_current_user_handles_no_login(monkeypatch: pytest.MonkeyPatch) -> None:
    """When every env source is empty, ``getpass.getuser`` is the fallback."""
    monkeypatch.delenv("HMP_USER", raising=False)
    monkeypatch.delenv("USER", raising=False)
    monkeypatch.delenv("USERNAME", raising=False)
    monkeypatch.delenv("LOGNAME", raising=False)
    monkeypatch.setattr("getpass.getuser", lambda: "fallback_user")
    result = LocalAuthBackend().current_user()
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
    result = LocalAuthBackend().current_user()
    assert result == "anonymous"
