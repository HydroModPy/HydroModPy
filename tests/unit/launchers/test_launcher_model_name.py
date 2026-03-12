"""Unit tests for launcher model-name initialization from simulation config."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from hydromodpy.simulation.state.run_state import LauncherRunState
from launchers.process_simulation.launcher import HydroModPyLauncher


class _DummyWorkspace:
    def __init__(self, config) -> None:
        self.config = config
        self.catch_folder = Path("workspace")
        self.stable_folder = self.catch_folder / "results_stable"
        self.simulations_folder = self.catch_folder / "results_simulations"


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


def _standard_geographic_cfg() -> SimpleNamespace:
    return SimpleNamespace(uses_synthetic_geographic=lambda: False)


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
        geographic=_standard_geographic_cfg(),
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


def test_run_setup_replaces_spaces_in_simulation_name(monkeypatch) -> None:
    _patch_launcher_deps(monkeypatch)

    cfg = SimpleNamespace(
        workspace=SimpleNamespace(),
        geographic=_standard_geographic_cfg(),
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
        geographic=_standard_geographic_cfg(),
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


def test_run_setup_builds_synthetic_geographic_when_requested(monkeypatch) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        "launchers.process_simulation.launcher.hmp.Workspace",
        _DummyWorkspace,
    )
    monkeypatch.setattr(
        "launchers.process_simulation.launcher.Domain",
        _DummyDomain,
    )

    def _unexpected_geographic(*args, **kwargs):
        raise AssertionError("standard geographic runtime should not be built")

    monkeypatch.setattr(
        "launchers.process_simulation.launcher.hmp.Geographic",
        _unexpected_geographic,
    )

    synthetic_runtime = _DummyGeographic(config=None, workspace=None)

    def _fake_build_synthetic_geographic(*, config, output_dir, workspace):
        captured["config"] = config
        captured["output_dir"] = output_dir
        captured["workspace"] = workspace
        return synthetic_runtime

    monkeypatch.setattr(
        "launchers.process_simulation.launcher.build_synthetic_geographic",
        _fake_build_synthetic_geographic,
    )
    monkeypatch.setattr(
        "launchers.process_simulation.launcher.apply_catchment_zones_to_domain",
        lambda **kwargs: None,
    )

    geographic_cfg = SimpleNamespace(
        synthetic=SimpleNamespace(case_id="synthetic_launcher"),
        uses_synthetic_geographic=lambda: True,
    )
    cfg = SimpleNamespace(
        workspace=SimpleNamespace(),
        geographic=geographic_cfg,
        domain=SimpleNamespace(zone_ids=[]),
        simulation=SimpleNamespace(name="simulation_name_from_toml"),
    )
    run_state = LauncherRunState(
        cfg=cfg,
        config_path=Path("config.toml"),
        raw_toml={},
    )

    monkeypatch.setattr(
        "launchers.process_simulation.launcher.ensure_flow",
        _noop_ensure,
    )
    monkeypatch.setattr(
        "launchers.process_simulation.launcher.ensure_transport",
        _noop_ensure,
    )

    launcher = HydroModPyLauncher.__new__(HydroModPyLauncher)
    launcher.cfg = cfg
    launcher.run_state = run_state

    launcher._run_setup()

    assert run_state.setup.geographic is synthetic_runtime
    assert captured["config"] is geographic_cfg.synthetic
    assert captured["workspace"] is run_state.setup.workspace
    assert captured["output_dir"] == Path("workspace") / "results_stable" / "geographic"


def test_run_setup_does_not_declare_unused_geology_zone(monkeypatch) -> None:
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
        "launchers.process_simulation.launcher.apply_catchment_zones_to_domain",
        lambda **kwargs: None,
    )

    cfg = SimpleNamespace(
        workspace=SimpleNamespace(),
        geographic=_standard_geographic_cfg(),
        domain=SimpleNamespace(zone_ids=[]),
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
    launcher.data_plan = SimpleNamespace(types=("geology",))
    launcher.process_context_factory = SimpleNamespace(
        ensure_flow=lambda state: None,
        ensure_transport=lambda state: None,
    )

    launcher._run_setup()

    assert run_state.setup.domain.config.zone_ids == ["catchment"]


def test_run_setup_declares_requested_geology_support_id(monkeypatch) -> None:
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
        "launchers.process_simulation.launcher.apply_catchment_zones_to_domain",
        lambda **kwargs: None,
    )

    cfg = SimpleNamespace(
        workspace=SimpleNamespace(),
        geographic=_standard_geographic_cfg(),
        domain=SimpleNamespace(zone_ids=[]),
        simulation=SimpleNamespace(name="simulation_name_from_toml"),
    )
    run_state = LauncherRunState(
        cfg=cfg,
        config_path=Path("config.toml"),
        raw_toml={},
    )

    def _ensure_flow(state) -> None:
        state.setup.flow = SimpleNamespace(
            parameters={
                "K": SimpleNamespace(
                    is_heterogeneous=True,
                    field_spatial_id="field_geology",
                )
            }
        )

    launcher = HydroModPyLauncher.__new__(HydroModPyLauncher)
    launcher.cfg = cfg
    launcher.run_state = run_state
    launcher.data_plan = SimpleNamespace(types=("geology",))
    launcher.requested_spatial_support_ids = ("field_geology",)
    launcher.requested_domain_supports = {
        "field_geology": SimpleNamespace(provider="geology")
    }
    launcher._build_domain_spatial_supports = lambda *, phase: None
    launcher.process_context_factory = SimpleNamespace(
        ensure_flow=_ensure_flow,
        ensure_transport=lambda state: None,
    )

    launcher._run_setup()

    assert run_state.setup.domain.config.zone_ids == ["catchment", "field_geology"]


def test_run_setup_rejects_heterogeneous_flow_when_support_is_undeclared(monkeypatch) -> None:
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
        "launchers.process_simulation.launcher.apply_catchment_zones_to_domain",
        lambda **kwargs: None,
    )

    cfg = SimpleNamespace(
        workspace=SimpleNamespace(),
        geographic=_standard_geographic_cfg(),
        domain=SimpleNamespace(zone_ids=[]),
        simulation=SimpleNamespace(name="simulation_name_from_toml"),
    )
    run_state = LauncherRunState(
        cfg=cfg,
        config_path=Path("config.toml"),
        raw_toml={},
    )

    def _ensure_flow(state) -> None:
        state.setup.flow = SimpleNamespace(
            parameters={
                "K": SimpleNamespace(
                    is_heterogeneous=True,
                    field_spatial_id="field_geology",
                )
            }
        )

    launcher = HydroModPyLauncher.__new__(HydroModPyLauncher)
    launcher.cfg = cfg
    launcher.run_state = run_state
    launcher.data_plan = SimpleNamespace(types=())
    launcher.requested_spatial_support_ids = ("field_geology",)
    launcher.requested_domain_supports = {}
    launcher.process_context_factory = SimpleNamespace(
        ensure_flow=_ensure_flow,
        ensure_transport=lambda state: None,
    )

    with pytest.raises(ValueError, match="domain.supports"):
        launcher._run_setup()
