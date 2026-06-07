"""Unit tests for the V1 authentication backends and selector."""

from __future__ import annotations

import pytest

from hydromodpy.core.auth import AuthBackend, LocalAuthBackend, get_auth_backend


def test_local_auth_backend_satisfies_protocol() -> None:
    """``LocalAuthBackend`` is an :class:`AuthBackend`."""
    assert isinstance(LocalAuthBackend(), AuthBackend)


def test_local_auth_backend_uses_hmp_user(monkeypatch: pytest.MonkeyPatch) -> None:
    """``HMP_USER`` wins over every other source."""
    monkeypatch.setenv("HMP_USER", "researcher")
    monkeypatch.setenv("USER", "ignored")
    assert LocalAuthBackend().current_user() == "researcher"


def test_local_auth_backend_falls_back_to_posix_user(monkeypatch: pytest.MonkeyPatch) -> None:
    """When ``HMP_USER`` is absent, ``USER`` (POSIX) is consulted."""
    monkeypatch.delenv("HMP_USER", raising=False)
    monkeypatch.setenv("USER", "alice")
    assert LocalAuthBackend().current_user() == "alice"


def test_local_auth_backend_falls_back_to_windows_username(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When ``USER`` is also absent, ``USERNAME`` (Windows) is consulted."""
    monkeypatch.delenv("HMP_USER", raising=False)
    monkeypatch.delenv("USER", raising=False)
    monkeypatch.setenv("USERNAME", "bob")
    assert LocalAuthBackend().current_user() == "bob"


def test_local_auth_backend_allows_read_and_write() -> None:
    """The permissive default authorises every resource."""
    backend = LocalAuthBackend()
    assert backend.can_read("catalog:project:naizin") is True
    assert backend.can_write("catalog:sim:abc") is True


def test_get_auth_backend_defaults_to_local(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without env var or explicit name, ``get_auth_backend`` returns local."""
    monkeypatch.delenv("HMP_AUTH_BACKEND", raising=False)
    backend = get_auth_backend()
    assert isinstance(backend, LocalAuthBackend)


def test_get_auth_backend_honours_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    """``HMP_AUTH_BACKEND=local`` selects the local backend."""
    monkeypatch.setenv("HMP_AUTH_BACKEND", "local")
    backend = get_auth_backend()
    assert isinstance(backend, LocalAuthBackend)


def test_get_auth_backend_rejects_unknown_name() -> None:
    """An unknown backend key raises ``ValueError`` listing valid names."""
    with pytest.raises(ValueError, match="local"):
        get_auth_backend(name="iam")
