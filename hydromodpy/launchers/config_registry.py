"""Public registry of launcher-specific config sections.

This keeps launcher-only config wiring behind the canonical
``hydromodpy.launchers`` namespace so core modules do not reach directly into
legacy ``launchers.*`` internals.
"""

from __future__ import annotations

from pydantic import BaseModel

_LAUNCHER_CONFIG_REGISTRY: dict[str, type[BaseModel]] | None = None


def launcher_config_registry() -> dict[str, type[BaseModel]]:
    """Return launcher-owned config models exposed through the public facade."""
    global _LAUNCHER_CONFIG_REGISTRY
    if _LAUNCHER_CONFIG_REGISTRY is None:
        from launchers.data_overview.config import OverviewSection
        from launchers.mesh_catchment.config import (
            MeshCatchmentBatchSectionSchema,
            MeshCatchmentConfigSchema,
        )

        _LAUNCHER_CONFIG_REGISTRY = {
            "mesh_catchment": MeshCatchmentConfigSchema,
            "mesh_catchment_batch": MeshCatchmentBatchSectionSchema,
            "overview": OverviewSection,
        }
    return dict(_LAUNCHER_CONFIG_REGISTRY)


__all__ = ["launcher_config_registry"]
