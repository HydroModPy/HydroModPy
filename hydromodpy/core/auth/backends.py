"""Concrete authentication backends bundled with V1."""

from __future__ import annotations

import getpass
import os


class LocalAuthBackend:
    """Permissive backend driven by the local OS session.

    Resolves the current user via ``HMP_USER`` (override), ``USER`` /
    ``USERNAME`` (POSIX / Windows env), then :func:`getpass.getuser`.
    Allows every read and write. The class exists in V1 so the catalog
    can route through an :class:`~hydromodpy.core.auth.protocol.AuthBackend`
    abstraction without yet enforcing real ACLs.
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
