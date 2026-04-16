"""HydroModPy launcher facade.

The historical top-level ``launchers`` package remains supported for backward
compatibility.  This facade provides the canonical import path under the main
``hydromodpy`` namespace:

    from hydromodpy.launchers import HydroModPyLauncher
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hydromodpy.core.state.run_state import LauncherRunState
    from launchers.data_overview.launcher import DataOverviewLauncher
    from launchers.mesh_catchment.launcher import MeshCatchmentLauncher
    from launchers.method_comparison.launcher import MethodComparisonLauncher
    from launchers.model_calibration.launcher import ModelCalibrationLauncher
    from launchers.process_simulation.launcher import HydroModPyLauncher
    from launchers.regional_lab.launcher import RegionalLabLauncher

__all__ = [
    "DataOverviewLauncher",
    "HydroModPyLauncher",
    "LauncherRunState",
    "MeshCatchmentLauncher",
    "MethodComparisonLauncher",
    "ModelCalibrationLauncher",
    "RegionalLabLauncher",
]


def __getattr__(name: str):
    if name == "DataOverviewLauncher":
        from launchers.data_overview.launcher import DataOverviewLauncher

        return DataOverviewLauncher
    if name == "HydroModPyLauncher":
        from launchers.process_simulation.launcher import HydroModPyLauncher

        return HydroModPyLauncher
    if name == "MeshCatchmentLauncher":
        from launchers.mesh_catchment.launcher import MeshCatchmentLauncher

        return MeshCatchmentLauncher
    if name == "MethodComparisonLauncher":
        from launchers.method_comparison.launcher import MethodComparisonLauncher

        return MethodComparisonLauncher
    if name == "ModelCalibrationLauncher":
        from launchers.model_calibration.launcher import ModelCalibrationLauncher

        return ModelCalibrationLauncher
    if name == "RegionalLabLauncher":
        from launchers.regional_lab.launcher import RegionalLabLauncher

        return RegionalLabLauncher
    if name == "LauncherRunState":
        from hydromodpy.core.state.run_state import LauncherRunState

        return LauncherRunState
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(__all__)
