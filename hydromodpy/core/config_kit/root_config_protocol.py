"""Protocol decoupling core helpers from the application root config.

The 15x15 layer matrix forbids ``core -> config``. The config_kit
registry and JSON Schema exporter need the root Pydantic model to introspect
its fields. They consume that information through this Protocol; the concrete
provider is wired in at package bootstrap by :mod:`hydromodpy._bootstrap`.

Other layers consume the same Protocol when they need to build or validate a
root config from raw payloads without depending on ``hydromodpy.config``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel


class RootConfigProvider(Protocol):
    """Read-only access to the top-level configuration model class."""

    def root_model(self) -> type[BaseModel]:
        """Return the root Pydantic configuration class."""

    def from_toml(self, toml_path: str | Path) -> BaseModel:
        """Build a validated root-config instance from a TOML file path."""

    def from_json(self, payload: str | bytes) -> BaseModel:
        """Build a validated root-config instance from a JSON payload."""

    def from_dict(self, payload: dict[str, Any]) -> BaseModel:
        """Build a validated root-config instance from a Python dict."""

    def migrate_on_load(
        self, payload: dict[str, Any], *, source: str | Path | None = None
    ) -> list[str]:
        """Migrate a raw TOML payload written for an earlier schema, in memory.

        Rewrites ``payload`` in place and returns the changes applied. Raises
        :class:`ValueError` on a legacy key that has no exact equivalent.
        """


_PROVIDER: RootConfigProvider | None = None


def set_root_config_provider(provider: RootConfigProvider) -> None:
    """Install the root-config provider used by core config helpers."""
    global _PROVIDER
    _PROVIDER = provider


def get_root_config_provider() -> RootConfigProvider:
    """Return the installed provider, running the lazy bootstrap if needed."""
    if _PROVIDER is None:
        from hydromodpy.core.bootstrap_hook import ensure_bootstrapped

        ensure_bootstrapped()
    if _PROVIDER is None:
        raise RuntimeError(
            "Root-config provider not installed. "
            "Did you forget to import hydromodpy (which registers the bootstrap hook)?"
        )
    return _PROVIDER


__all__ = (
    "RootConfigProvider",
    "get_root_config_provider",
    "set_root_config_provider",
)
