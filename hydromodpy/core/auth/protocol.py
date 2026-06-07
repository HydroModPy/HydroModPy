"""Structural protocol every authentication backend honours."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class AuthBackend(Protocol):
    """Minimal authn + authz surface relied on by the catalog layer.

    A backend resolves *who* is acting (``current_user``) and answers
    yes-or-no on access to a logical resource. Resources are identified
    by opaque strings (e.g. ``"catalog:project:naizin"``); each backend
    decides how to map them onto its own access model.
    """

    def current_user(self) -> str:
        """Return the textual identifier of the principal in this session."""

    def can_read(self, resource: str) -> bool:
        """Return ``True`` if the current user may read ``resource``."""

    def can_write(self, resource: str) -> bool:
        """Return ``True`` if the current user may write ``resource``."""
