"""Authentication and authorization backends for HydroModPy.

Defines :class:`AuthBackend`, a structural :class:`typing.Protocol` that
every concrete backend implements (e.g. :class:`LocalAuthBackend`).

V1 ships only a permissive :class:`LocalAuthBackend` that reports the
current OS user and allows every operation. Real backends (keyring-backed
secrets, IAM roles, SSO) are V2 work; the abstraction exists now so the
catalog layer can wire callsites without later refactor.
"""

from __future__ import annotations

import getpass
import os
from typing import Protocol, runtime_checkable


@runtime_checkable
class AuthBackend(Protocol):
    """Minimal authn + authz surface relied on by the catalog layer.

    A backend resolves *who* is acting (``current_user``) and answers
    yes-or-no on access to a logical resource. Resources are identified
    by opaque strings (e.g. ``"catalog:project:my_project"``); each backend
    decides how to map them onto its own access model.
    """

    def current_user(self) -> str:
        """Return the textual identifier of the principal in this session."""

    def can_read(self, resource: str) -> bool:
        """Return ``True`` if the current user may read ``resource``."""

    def can_write(self, resource: str) -> bool:
        """Return ``True`` if the current user may write ``resource``."""


class LocalAuthBackend:
    """Permissive backend driven by the local OS session.

    Resolves the current user via ``HMP_USER`` (override), ``USER`` /
    ``USERNAME`` (POSIX / Windows env), then :func:`getpass.getuser`.
    Allows every read and write. The class exists in V1 so the catalog
    can route through an :class:`AuthBackend` abstraction without yet
    enforcing real ACLs.
    """

    def current_user(self) -> str:
        override = os.environ.get("HMP_USER")
        if override:
            return override
        for env in ("USER", "USERNAME"):
            value = os.environ.get(env)
            if value:
                return value
        try:
            return getpass.getuser()
        except OSError:
            return "anonymous"

    def can_read(self, resource: str) -> bool:  # noqa: ARG002
        return True

    def can_write(self, resource: str) -> bool:  # noqa: ARG002
        return True


_BACKENDS: dict[str, type[AuthBackend]] = {
    "local": LocalAuthBackend,
}


def get_auth_backend(name: str | None = None) -> AuthBackend:
    """Return the auth backend matching ``name`` or ``HMP_AUTH_BACKEND``.

    Defaults to the permissive :class:`LocalAuthBackend`. Raises
    ``ValueError`` when an unknown backend name is requested so misspelt
    deployment configs fail loudly.
    """
    key = (name or os.environ.get("HMP_AUTH_BACKEND") or "local").lower()
    try:
        cls = _BACKENDS[key]
    except KeyError as exc:
        known = ", ".join(sorted(_BACKENDS))
        raise ValueError(f"Unknown HMP_AUTH_BACKEND={key!r}; available backends: {known}") from exc
    return cls()


__all__ = ["AuthBackend", "LocalAuthBackend", "get_auth_backend"]
