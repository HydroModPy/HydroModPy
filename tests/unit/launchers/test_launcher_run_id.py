"""Unit tests for launcher run_id initialization from simulation config."""

from __future__ import annotations

from pathlib import Path
import shutil
import tempfile
from types import SimpleNamespace

import pytest

from hydromodpy.simulation.state.run_state import LauncherRunState

from launchers.process_simulation.launcher import HydroModPyLauncher


class _DummyWorkspace:
    def __init__(self, config) -> None:
        self.config = config
        self.project_root = Path("workspace")
        self.catch_folder = self.project_root
        self.stable_folder = self.project_root / "results_stable"
        self.simulations_folder = self.project_root / "results_simulations"


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


def test_run_setup_uses_simulation_run_id(monkeypatch) -> None:
    _patch_launcher_deps(monkeypatch)

    cfg = SimpleNamespace(
        workspace=SimpleNamespace(),
        geographic=_standard_geographic_cfg(),
        domain=SimpleNamespace(),
        simulation=SimpleNamespace(run_id="my_run_id"),
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

    assert run_state.setup.run_id == "my_run_id"


def test_run_setup_defaults_run_id_when_empty(monkeypatch) -> None:
    _patch_launcher_deps(monkeypatch)

    cfg = SimpleNamespace(
        workspace=SimpleNamespace(),
        geographic=_standard_geographic_cfg(),
        domain=SimpleNamespace(),
        simulation=SimpleNamespace(run_id=""),
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

    assert run_state.setup.run_id == "default"


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
        simulation=SimpleNamespace(run_id="test"),
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
        simulation=SimpleNamespace(run_id="test"),
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


def test_process_launcher_rejects_embedded_mesh_catchment_batch_section() -> None:
    launcher = HydroModPyLauncher.__new__(HydroModPyLauncher)

    with pytest.raises(ValueError, match="Embedded \\[mesh_catchment_batch\\] is not supported"):
        launcher._resolve_optional_mesh_section(
            {
                "mesh_catchment": {"constraints_mode": "rivers_only"},
                "mesh_catchment_batch": {
                    "enabled": True,
                    "outlets_table_path": "outlets.csv",
                },
            }
        )


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
    monkeypatch.setattr(
        "launchers.process_simulation.launcher.ensure_flow",
        lambda state: None,
    )
    monkeypatch.setattr(
        "launchers.process_simulation.launcher.ensure_transport",
        lambda state: None,
    )

    cfg = SimpleNamespace(
        workspace=SimpleNamespace(),
        geographic=_standard_geographic_cfg(),
        domain=SimpleNamespace(zone_ids=[]),
        simulation=SimpleNamespace(run_id="test"),
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
        simulation=SimpleNamespace(run_id="test"),
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

    monkeypatch.setattr(
        "launchers.process_simulation.launcher.ensure_flow",
        _ensure_flow,
    )
    monkeypatch.setattr(
        "launchers.process_simulation.launcher.ensure_transport",
        lambda state: None,
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
        simulation=SimpleNamespace(run_id="test"),
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

    monkeypatch.setattr(
        "launchers.process_simulation.launcher.ensure_flow",
        _ensure_flow,
    )
    monkeypatch.setattr(
        "launchers.process_simulation.launcher.ensure_transport",
        lambda state: None,
    )

    launcher = HydroModPyLauncher.__new__(HydroModPyLauncher)
    launcher.cfg = cfg
    launcher.run_state = run_state
    launcher.data_plan = SimpleNamespace(types=())
    launcher.requested_spatial_support_ids = ("field_geology",)
    launcher.requested_domain_supports = {}

    with pytest.raises(ValueError, match="domain.supports"):
        launcher._run_setup()


def test_run_executes_embedded_mesh_phase_and_records_metrics(monkeypatch) -> None:
    workspace_root = Path(
        tempfile.mkdtemp(prefix="mesh-sim-int-")
    ).resolve()
    config_path = workspace_root / "simulation_with_mesh.toml"

    class _DummyDataConfig:
        types: tuple[str, ...] = ()

        def with_resolved_types(self, types):
            _ = types
            return self

    class _DummySimulationConfig:
        run_id = "mesh_run"

        @staticmethod
        def has_processes() -> bool:
            return True

    cfg = SimpleNamespace(
        workspace=SimpleNamespace(project_root=workspace_root / "project"),
        geographic=SimpleNamespace(
            uses_synthetic_geographic=lambda: False,
            river_network=SimpleNamespace(enabled=False),
        ),
        domain=SimpleNamespace(zone_ids=[], supports={}),
        data=_DummyDataConfig(),
        flow=SimpleNamespace(active_bc=(), param={}),
        postprocess=SimpleNamespace(),
        simulation=_DummySimulationConfig(),
    )

    class _DummyRunWorkspace:
        def __init__(self, config) -> None:
            self.config = config
            self.project_root = Path(config.project_root).resolve()
            self.stable_folder = self.project_root / "results_stable"
            self.simulations_folder = self.project_root / "results_simulations"

    class _DummyRunGeographic:
        def __init__(self, config, workspace) -> None:
            self.config = config
            self.workspace = workspace

        def get_domain_geographic_context(self):
            return SimpleNamespace(
                surface_topo=object(),
                river_mesh_trace="river-trace",
            )

    class _DummyRunDomain:
        def __init__(self, config, surface_topo) -> None:
            self.config = config
            self.surface_topo = surface_topo

    class _DummyPlanner:
        def build(self, *args, **kwargs):
            _ = args, kwargs
            return SimpleNamespace(
                inferred_types=(),
                types=(),
                reasons_for=lambda type_name: (),
            )

    class _DummyRuntimeLoader:
        def __init__(self, *args, **kwargs) -> None:
            _ = args, kwargs

        def load_all(self, run_state) -> None:
            _ = run_state

    class _DummyPostprocessRunner:
        def __init__(self, cfg) -> None:
            _ = cfg

        def after_process(self, process_type, run_state) -> None:
            _ = process_type, run_state

    class _DummySimulationPlanner:
        def build(self, simulation_cfg):
            _ = simulation_cfg
            return SimpleNamespace(runs=[])

    executed: dict[str, object] = {}
    captured_artifacts: dict[str, object] = {}

    class _DummySimulationRunner:
        def __init__(self, callbacks) -> None:
            executed["callbacks"] = callbacks

        def execute(self, plan, run_state) -> None:
            executed["plan"] = plan
            executed["run_state"] = run_state

    captured_mesh: dict[str, object] = {}

    def _fake_mesh_workflow(**kwargs):
        captured_mesh.update(kwargs)
        return {
            "constraints_mode": "rivers_only",
            "output_mesh": "workspace/results_stable/mesh/mesh_catchment.msh",
            "output_summary_json": "workspace/results_stable/mesh/mesh_catchment_summary.json",
        }

    monkeypatch.setattr(
        "launchers.process_simulation.launcher.HydroModPyConfig.from_toml",
        lambda _: cfg,
    )
    monkeypatch.setattr(
        "launchers.process_simulation.launcher.apply_explicit_time_window_to_tgrids",
        lambda _: None,
    )
    monkeypatch.setattr(
        "launchers.process_simulation.launcher.require_flow_simulation_time_grid",
        lambda _: SimpleNamespace(window=SimpleNamespace()),
    )
    monkeypatch.setattr(
        "launchers.process_simulation.launcher.load_toml_with_base_config",
        lambda _: {"mesh_catchment": {"constraints_mode": "rivers_only"}},
    )
    monkeypatch.setattr(
        "launchers.process_simulation.launcher.prepare_geographic_config_for_meshing",
        lambda geographic_cfg, *, constraints_mode: geographic_cfg,
    )
    monkeypatch.setattr(
        "launchers.process_simulation.launcher.build_default_spatial_support_provider_registry",
        lambda: {},
    )
    monkeypatch.setattr(
        "launchers.process_simulation.launcher._build_data_plan",
        lambda *args, **kwargs: _DummyPlanner().build(*args, **kwargs),
    )
    monkeypatch.setattr(
        "launchers.process_simulation.launcher.PostprocessRunner",
        _DummyPostprocessRunner,
    )
    monkeypatch.setattr(
        "launchers.process_simulation.launcher.hmp.Workspace",
        _DummyRunWorkspace,
    )
    monkeypatch.setattr(
        "launchers.process_simulation.launcher.hmp.Geographic",
        _DummyRunGeographic,
    )
    monkeypatch.setattr(
        "launchers.process_simulation.launcher.Domain",
        _DummyRunDomain,
    )
    monkeypatch.setattr(
        "launchers.process_simulation.launcher.apply_catchment_zones_to_domain",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        "launchers.process_simulation.launcher.ensure_flow",
        lambda state: setattr(state.setup, "flow", SimpleNamespace(parameters={})),
    )
    monkeypatch.setattr(
        "launchers.process_simulation.launcher.ensure_transport",
        lambda state: setattr(state.setup, "transport", SimpleNamespace()),
    )
    monkeypatch.setattr(
        "launchers.process_simulation.launcher._build_data_runtime_loader",
        lambda *args, **kwargs: _DummyRuntimeLoader(*args, **kwargs),
    )
    monkeypatch.setattr(
        "launchers.process_simulation.launcher.apply_geology_to_domain",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        "launchers.process_simulation.launcher.apply_oceanic_to_flow",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        "launchers.process_simulation.launcher.apply_recharge_load_result_to_flow",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        "launchers.process_simulation.launcher.SimulationPlanner",
        lambda: _DummySimulationPlanner(),
    )
    monkeypatch.setattr(
        "launchers.process_simulation.launcher.SimulationRunner",
        _DummySimulationRunner,
    )
    monkeypatch.setattr(
        "launchers.process_simulation.launcher.run_single_mesh_catchment_workflow",
        _fake_mesh_workflow,
    )
    monkeypatch.setattr(
        "launchers.process_simulation.launcher.HydroModPyLauncher._save_run_artifacts",
        lambda self, run_state, wall_seconds: captured_artifacts.update(
            {
                "mesh_summary": run_state.setup.mesh_summary,
                "wall_seconds": wall_seconds,
            }
        ),
    )

    try:
        launcher = HydroModPyLauncher(config_path)
        run_state = launcher.run()

        assert executed["run_state"] is run_state
        assert captured_mesh["constraints_mode"] == "rivers_only"
        assert captured_mesh["workspace"] is run_state.setup.workspace
        assert captured_mesh["domain_geographic"] is run_state.setup.domain_geographic
        assert run_state.setup.mesh_summary is not None
        assert (
            captured_artifacts["mesh_summary"]["output_mesh"]
            == "workspace/results_stable/mesh/mesh_catchment.msh"
        )
    finally:
        shutil.rmtree(workspace_root, ignore_errors=True)
