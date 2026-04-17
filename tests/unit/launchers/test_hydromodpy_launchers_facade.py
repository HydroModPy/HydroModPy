from __future__ import annotations

import hydromodpy.launchers as hydromodpy_launchers
import launchers as legacy_launchers

from hydromodpy.launchers import (
    DataOverviewLauncher,
    HydroModPyLauncher,
    LauncherRunState,
    MeshCatchmentLauncher,
    MethodComparisonLauncher,
    ModelCalibrationLauncher,
    RegionalLabLauncher,
)
from hydromodpy.launchers.config_registry import launcher_config_registry
from hydromodpy.launchers.data_overview import (
    DataOverviewConfig,
    DataOverviewState,
    OverviewSection,
)


def test_hydromodpy_launchers_facade_resolves_public_classes() -> None:
    from hydromodpy.core.state.run_state import LauncherRunState as _RunState
    from launchers.data_overview.launcher import DataOverviewLauncher as _Overview
    from launchers.mesh_catchment.launcher import MeshCatchmentLauncher as _Mesh
    from launchers.method_comparison.launcher import (
        MethodComparisonLauncher as _MethodComparison,
    )
    from launchers.model_calibration.launcher import (
        ModelCalibrationLauncher as _Calibration,
    )
    from launchers.process_simulation.launcher import HydroModPyLauncher as _Run
    from launchers.regional_lab.launcher import RegionalLabLauncher as _Regional

    assert DataOverviewLauncher is _Overview
    assert HydroModPyLauncher is _Run
    assert LauncherRunState is _RunState
    assert MeshCatchmentLauncher is _Mesh
    assert MethodComparisonLauncher is _MethodComparison
    assert ModelCalibrationLauncher is _Calibration
    assert RegionalLabLauncher is _Regional


def test_hydromodpy_data_overview_facade_resolves_public_types() -> None:
    from launchers.data_overview.config import (
        DataOverviewConfig as _Config,
        OverviewSection as _Section,
    )
    from launchers.data_overview.state import DataOverviewState as _State

    assert DataOverviewConfig is _Config
    assert DataOverviewState is _State
    assert OverviewSection is _Section


def test_launcher_config_registry_exposes_launcher_sections() -> None:
    registry = launcher_config_registry()

    assert set(registry) >= {"mesh_catchment", "mesh_catchment_batch", "overview"}
    assert registry["overview"] is OverviewSection


def test_hydromodpy_launchers_facade_honors_legacy_overrides(monkeypatch) -> None:
    class DummyLauncher:
        pass

    monkeypatch.setattr(legacy_launchers, "HydroModPyLauncher", DummyLauncher)

    assert hydromodpy_launchers.HydroModPyLauncher is DummyLauncher
