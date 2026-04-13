"""HydroModPy launchers top-level convenience re-exports.

This module uses lazy imports so mesh-catchment CLI/tests stay importable
without pulling the full simulation/data-manager stack unless needed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hydromodpy.core.state.run_state import LauncherRunState
    from hydromodpy.workflow.pipelines.overview import DataOverviewLauncher
    from hydromodpy.workflow.pipelines.mesh import MeshCatchmentLauncher
    from launchers.method_comparison.launcher import MethodComparisonLauncher
    from hydromodpy.analysis.calibration.engine.launcher import ModelCalibrationLauncher
    from launchers.process_simulation.launcher import HydroModPyLauncher
    from hydromodpy.analysis.batch.runtime import RegionalLabLauncher

__all__ = [
    "DataOverviewLauncher",
    "HydroModPyLauncher",
    "MeshCatchmentLauncher",
    "MethodComparisonLauncher",
    "ModelCalibrationLauncher",
    "RegionalLabLauncher",
    "LauncherRunState",
]


def __getattr__(name: str):
    if name == "DataOverviewLauncher":
        from hydromodpy.workflow.pipelines.overview import DataOverviewLauncher

        return DataOverviewLauncher
    if name == "HydroModPyLauncher":
        from launchers.process_simulation.launcher import HydroModPyLauncher

        return HydroModPyLauncher
    if name == "MeshCatchmentLauncher":
        from hydromodpy.workflow.pipelines.mesh import MeshCatchmentLauncher

        return MeshCatchmentLauncher
    if name == "MethodComparisonLauncher":
        from launchers.method_comparison.launcher import MethodComparisonLauncher

        return MethodComparisonLauncher
    if name == "ModelCalibrationLauncher":
        from hydromodpy.analysis.calibration.engine.launcher import ModelCalibrationLauncher

        return ModelCalibrationLauncher
    if name == "RegionalLabLauncher":
        from hydromodpy.analysis.batch.runtime import RegionalLabLauncher

        return RegionalLabLauncher
    if name == "LauncherRunState":
        from hydromodpy.core.state.run_state import LauncherRunState

        return LauncherRunState
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(__all__)
