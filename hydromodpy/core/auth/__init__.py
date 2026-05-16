"""Authentication and authorisation backends for HydroModPy.

Defines :class:`AuthBackend`, a structural :class:`typing.Protocol` that
every concrete backend implements (e.g. :class:`LocalAuthBackend`).

V1 ships only a permissive :class:`LocalAuthBackend` that reports the
current OS user and allows every operation. Real backends (keyring-backed
secrets, IAM roles, SSO) are V2 work; the abstraction exists now so the
catalog layer can wire callsites without later refactor.
"""

from __future__ import annotations

from hydromodpy.core.auth.backends import LocalAuthBackend
from hydromodpy.core.auth.protocol import AuthBackend
from hydromodpy.core.auth.selection import get_auth_backend

__all__ = ["AuthBackend", "LocalAuthBackend", "get_auth_backend"]
