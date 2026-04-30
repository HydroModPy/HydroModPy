"""Protocol contracts for the spatial layer.

Spatial modules access data-layer services through Protocols defined here so
the spatial package never imports the data package at module load time.
The bootstrap registers the concrete implementations during application
start-up; spatial code resolves them with the ``get_*`` helpers.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class GeologyDataSource(Protocol):
    """Read-only access to geology configuration and encoded grids."""

    def validate_config(self, config: Mapping[str, Any]) -> dict[str, Any]:
        """Validate one raw geology config mapping into a normalized dict."""

    def load_encoded_grid(self, config: Mapping[str, Any]) -> dict[str, Any]:
        """Load one geology source and return its encoded grid record."""

    def load_encoded_grid_on_raster_support(
        self,
        config: Mapping[str, Any],
        *,
        raster_support: object,
    ) -> dict[str, Any]:
        """Load one geology source and project it onto an explicit raster support."""

    def load_toml(self, toml_path: str | Path, section: str = "geology") -> dict[str, Any]:
        """Load and validate one geology TOML section into a config dict."""

    def load_vector_dataframe(
        self,
        config: Mapping[str, Any],
        *,
        config_path: str | Path | None = None,
        zone_key_column: str = "zone_key",
    ) -> dict[str, Any]:
        """Load one vector geology source as a GeoDataFrame payload."""

    def resolve_data_path(
        self,
        data_path: str,
        *,
        config_path: str | Path | None = None,
    ) -> str:
        """Resolve one geology data path against repo root or config folder."""

    def normalize_zone_key(self, raw: Any) -> str:
        """Normalize one raw geology code into a stable string zone key."""


_geology_data_source: GeologyDataSource | None = None


def register_geology_data_source(source: GeologyDataSource) -> None:
    """Register the concrete geology data source provided by the data layer."""
    global _geology_data_source
    _geology_data_source = source


def get_geology_data_source() -> GeologyDataSource:
    """Return the registered geology data source, or raise if none is wired."""
    if _geology_data_source is None:
        raise RuntimeError(
            "GeologyDataSource is not registered. "
            "Import 'hydromodpy' (or call hydromodpy.bootstrap()) before "
            "using spatial helpers that consume geology data."
        )
    return _geology_data_source


__all__ = [
    "GeologyDataSource",
    "get_geology_data_source",
    "register_geology_data_source",
]
