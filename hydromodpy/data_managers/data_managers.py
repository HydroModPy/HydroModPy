"""Runtime container for active data-manager families.

This class is intentionally small: it currently stores only the ordered list
of active manager types declared in configuration (`data.types`).
"""

from __future__ import annotations

from dataclasses import dataclass

from hydromodpy.data_managers.data_managers_config import DataManagersConfig


@dataclass(slots=True)
class DataManagers:
    """Runtime view of the configured data-manager types."""

    types: list[str]

    @classmethod
    def from_config(cls, config: DataManagersConfig) -> "DataManagers":
        """Build runtime container from validated `DataManagersConfig`."""
        return cls(types=list(config.types))
