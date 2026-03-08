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

    def get_domain_geographic_context(self):
        return SimpleNamespace(
            surface_topo=self.get_domain_surface_topo(),
            watershed_shp="watershed.shp",
            catchment_area_km2=1.0,
            catch_def="from_outlet_coord",
            x_outlet=1.0,
            y_outlet=2.0,
            watershed_box_buff_dem="watershed_box_buff_dem.tif",
            box_buff_shp="watershed_box_buff.shp",
            zone_kind="catchment",
        )


class _DummyDomain:
    def __init__(self, config, surface_topo) -> None:
        self.config = config
        self.surface_topo = surface_topo


def _noop_ensure(state):
    """No-op replacement for ensure_flow / ensure_transport in tests."""


def _patch_launcher_deps(monkeypatch):
    """Patch Workspace, Geographic, Domain, and ensure_* for launcher tests."""
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
    monkeypatch.setattr(
        "launchers.process_simulation.launcher.ensure_flow",
        _noop_ensure,
    )
    monkeypatch.setattr(
        "launchers.process_simulation.launcher.ensure_transport",
        _noop_ensure,
    )


def test_run_setup_uses_simulation_name_as_model_name(monkeypatch) -> None:
    _patch_launcher_deps(monkeypatch)

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

    launcher._run_setup()

    assert run_state.setup.model_name == "simulation_name_from_toml"
    assert run_state.setup.settings.model_name == "simulation_name_from_toml"


def test_run_setup_replaces_spaces_in_simulation_name(monkeypatch) -> None:
    _patch_launcher_deps(monkeypatch)

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

    launcher._run_setup()

    assert run_state.setup.model_name == "simulation_name_with_spaces"
    assert run_state.setup.settings.model_name == "simulation_name_with_spaces"


def test_run_setup_stores_explicit_domain_geographic_context(monkeypatch) -> None:
    captured: dict[str, object] = {}
    _patch_launcher_deps(monkeypatch)

    def _fake_apply_catchment_zones_to_domain(*, domain, geographic, zone_id="catchment"):
        captured["domain"] = domain
        captured["geographic"] = geographic
        captured["zone_id"] = zone_id

    monkeypatch.setattr(
        "launchers.process_simulation.launcher.apply_catchment_zones_to_domain",
        _fake_apply_catchment_zones_to_domain,
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

    launcher._run_setup()

    assert run_state.setup.domain_geographic is not None
    assert captured["domain"] is run_state.setup.domain
    assert captured["geographic"] is run_state.setup.domain_geographic
    assert captured["zone_id"] == "catchment"
