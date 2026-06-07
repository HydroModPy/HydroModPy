"""Auth backend selection driven by the ``HMP_AUTH_BACKEND`` env var."""

from __future__ import annotations

import os

from hydromodpy.core.auth.backends import LocalAuthBackend
from hydromodpy.core.auth.protocol import AuthBackend

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
