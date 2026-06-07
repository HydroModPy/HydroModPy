"""Runtime setup scope shared by launcher process runs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from hydromodpy.core.workspace import Workspace


@dataclass
class SetupContext:
    """Objects prepared during setup and reused by all runs.

    Most field types are ``Any`` because ``core`` cannot import from
    sibling layers (``physics``, ``spatial``). Concrete classes live in
    ``physics.flow``, ``physics.transport``, ``spatial.domain``,
    ``spatial.geographic`` and ``spatial.mesh.gmsh_grid``.
    """

    workspace: Workspace | None = None
    geographic: Any = None
    geographic_features: Any = None
    domain_geographic: Any = None
    domain: Any = None
    flow: Any = None
    transport: Any = None
    mesh_summary: dict[str, Any] | None = None
    mesh_bundle: Any = None
    mesh_planar: Any = None
    mesh_support: Any = None
    flow_runtime_overrides: dict[str, Any] | None = None
    run_id: str = "default"
    time_grid: Any = None
