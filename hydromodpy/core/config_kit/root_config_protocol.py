"""Protocol decoupling core helpers from the application root config.

The 14x14 layer matrix forbids ``core -> config``. The config_kit
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


_PROVIDER: RootConfigProvider | None = None


def set_root_config_provider(provider: RootConfigProvider) -> None:
    """Install the root-config provider used by core config helpers."""
    global _PROVIDER
    _PROVIDER = provider


def get_root_config_provider() -> RootConfigProvider:
    """Return the installed provider."""
    if _PROVIDER is None:
        raise RuntimeError(
            "Root-config provider not installed. "
            "Did you forget to import hydromodpy (which calls bootstrap())?"
        )
    return _PROVIDER


__all__ = (
    "RootConfigProvider",
    "get_root_config_provider",
    "set_root_config_provider",
)
