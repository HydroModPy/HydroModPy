"""Who is acting, for the commands that sign what they write.

V1 knows one actor, the local user. :class:`AuthBackend` reports the current
OS user and allows every read and write. A real backend (keyring-backed
secrets, IAM roles, SSO) would replace this class when it exists.
"""

from __future__ import annotations

import getpass
import os


class AuthBackend:
    """Permissive backend driven by the local OS session.

    Resolves the current user via ``HMP_USER`` (override), ``USER`` /
    ``USERNAME`` (POSIX / Windows env), then :func:`getpass.getuser`.
    Allows every read and write on a logical resource, named by an opaque
    string such as ``"catalog:project:my_project"``.
    """

    def current_user(self) -> str:
        """Return the textual identifier of the principal in this session."""
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
        """Return ``True`` if the current user may read ``resource``."""
        return True

    def can_write(self, resource: str) -> bool:  # noqa: ARG002
        """Return ``True`` if the current user may write ``resource``."""
        return True
