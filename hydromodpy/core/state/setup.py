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
    # The ``cfg.domain`` section ``domain`` was built from. A Project builds its
    # model phase once and drives several runs through it; a run defined by
    # another configuration - a thickness sweep, a run following an overridden
    # one - must not inherit the previous run's geometry, and this is what says
    # so. Identity, not equality: ``resolve_run_config`` hands back the declared
    # section itself when a run overrides nothing.
    domain_config_source: Any = None
    flow: Any = None
    transport: Any = None
    mesh_summary: dict[str, Any] | None = None
    mesh_bundle: Any = None
    mesh_planar: Any = None
    mesh_support: Any = None
    flow_runtime_overrides: dict[str, Any] | None = None
    run_id: str = "default"
    time_grid: Any = None
    # Delineated SFR reach traces keyed by network id (spatial.SfrReachTrace).
    # Computed once by the data step and re-bound onto every per-run Flow.
    sfr_reach_traces: dict[str, Any] | None = None
