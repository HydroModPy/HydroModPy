"""HydroModPy launchers top-level convenience re-exports.

This module uses lazy imports so mesh-catchment CLI/tests stay importable
without pulling the full simulation/data-manager stack unless needed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hydromodpy.simulation.state.run_state import LauncherRunState
    from launchers.mesh_catchment.launcher import MeshCatchmentLauncher
    from launchers.process_simulation.launcher import HydroModPyLauncher

__all__ = [
    "HydroModPyLauncher",
    "MeshCatchmentLauncher",
    "LauncherRunState",
]


def __getattr__(name: str):
    if name == "HydroModPyLauncher":
        from launchers.process_simulation.launcher import HydroModPyLauncher

        return HydroModPyLauncher
    if name == "MeshCatchmentLauncher":
        from launchers.mesh_catchment.launcher import MeshCatchmentLauncher

        return MeshCatchmentLauncher
    if name == "LauncherRunState":
        from hydromodpy.simulation.state.run_state import LauncherRunState

        return LauncherRunState
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(__all__)
