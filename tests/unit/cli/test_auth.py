"""The default authorization backend: who the user is, and what the user may touch.

The user comes from HMP_USER, then USER, USERNAME and LOGNAME, then the system login, then "anonymous".
Every resource is open to read and write.
"""

from __future__ import annotations

import pytest

from hydromodpy.cli.auth import AuthBackend

LOGIN_VARIABLES = ("HMP_USER", "USER", "USERNAME", "LOGNAME")


def clear_login(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in LOGIN_VARIABLES:
        monkeypatch.delenv(name, raising=False)


def test_user_from_the_environment(monkeypatch) -> None:
    monkeypatch.setenv("HMP_USER", "alice")
    monkeypatch.setenv("USER", "ignored")
    monkeypatch.setenv("USERNAME", "ignored")

    assert AuthBackend().current_user() == "alice"


def test_user_from_the_system_login(monkeypatch) -> None:
    clear_login(monkeypatch)
    monkeypatch.setattr("getpass.getuser", lambda: "fallback_user")

    assert AuthBackend().current_user() == "fallback_user"


def test_user_is_anonymous_without_a_login(monkeypatch) -> None:
    clear_login(monkeypatch)

    def no_terminal() -> str:
        raise OSError("no controlling terminal")

    monkeypatch.setattr("getpass.getuser", no_terminal)

    assert AuthBackend().current_user() == "anonymous"


def test_every_resource_is_open() -> None:
    backend = AuthBackend()

    assert backend.can_read("catalog:project:naizin") is True
    assert backend.can_write("catalog:sim:abc") is True
