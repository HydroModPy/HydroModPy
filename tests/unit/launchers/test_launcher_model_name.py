"""Unit tests for launcher model-name initialization from simulation config."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from hydromodpy.simulation.state.run_state import LauncherRunState
from launchers.process_simulation.launcher import HydroModPyLauncher


class _DummyWorkspace:
    def __init__(self, config) -> None:
        self.config = config


class _DummyGeographic:
    def __init__(self, config, workspace) -> None:
        self.config = config
        self.workspace = workspace

    def get_domain_surface_topo(self):
        return SimpleNamespace(support=object())


class _DummyDomain:
    def __init__(self, config, surface_topo) -> None:
        self.config = config
        self.surface_topo = surface_topo


def test_run_setup_uses_simulation_name_as_model_name(monkeypatch) -> None:
    monkeypatch.setattr(
        "launchers.process_simulation.launcher.hmp.Workspace",
        _DummyWorkspace,
    )
    monkeypatch.setattr(
        "launchers.process_simulation.launcher.hmp.Geographic",
        _DummyGeographic,
    )
    monkeypatch.setattr(
        "launchers.process_simulation.launcher.Domain",
        _DummyDomain,
    )

    cfg = SimpleNamespace(
        workspace=SimpleNamespace(),
        geographic=SimpleNamespace(),
        domain=SimpleNamespace(),
        simulation=SimpleNamespace(name="simulation_name_from_toml"),
    )
    run_state = LauncherRunState(
        cfg=cfg,
        config_path=Path("config.toml"),
        raw_toml={},
    )

    launcher = HydroModPyLauncher.__new__(HydroModPyLauncher)
    launcher.cfg = cfg
    launcher.run_state = run_state
    launcher.process_context_factory = SimpleNamespace(
        ensure_flow=lambda state: None,
        ensure_transport=lambda state: None,
    )

    launcher._run_setup()

    assert run_state.setup.model_name == "simulation_name_from_toml"
    assert run_state.setup.settings.model_name == "simulation_name_from_toml"


def test_run_setup_replaces_spaces_in_simulation_name(monkeypatch) -> None:
    monkeypatch.setattr(
        "launchers.process_simulation.launcher.hmp.Workspace",
        _DummyWorkspace,
    )
    monkeypatch.setattr(
        "launchers.process_simulation.launcher.hmp.Geographic",
        _DummyGeographic,
    )
    monkeypatch.setattr(
        "launchers.process_simulation.launcher.Domain",
        _DummyDomain,
    )

    cfg = SimpleNamespace(
        workspace=SimpleNamespace(),
        geographic=SimpleNamespace(),
        domain=SimpleNamespace(),
        simulation=SimpleNamespace(name="simulation  name   with spaces"),
    )
    run_state = LauncherRunState(
        cfg=cfg,
        config_path=Path("config.toml"),
        raw_toml={},
    )

    launcher = HydroModPyLauncher.__new__(HydroModPyLauncher)
    launcher.cfg = cfg
    launcher.run_state = run_state
    launcher.process_context_factory = SimpleNamespace(
        ensure_flow=lambda state: None,
        ensure_transport=lambda state: None,
    )

    launcher._run_setup()

    assert run_state.setup.model_name == "simulation_name_with_spaces"
    assert run_state.setup.settings.model_name == "simulation_name_with_spaces"
