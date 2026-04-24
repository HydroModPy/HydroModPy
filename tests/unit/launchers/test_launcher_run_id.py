"""Unit tests for workflow step run_id initialization from simulation config."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from hydromodpy.core.state.run_state import WorkflowContext
from hydromodpy.workflow.steps.mesh import step_mesh_input
from hydromodpy.workflow.steps.setup import step_setup


def _make_launcher_test_workspace_root(
    hydromodpy_test_scratch_root: Path,
    *,
    prefix: str,
) -> Path:
    base_dir = hydromodpy_test_scratch_root / "launcher_run_id"
    base_dir.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=prefix, dir=base_dir)).resolve()


class _DummyWorkspace:
    def __init__(self, config) -> None:
        self.config = config
        self.project_root = Path("workspace")
        self.solver_scratch_folder = self.project_root / ".solver_scratch"


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
    """Patch Workspace, Geographic, Domain, and ensure_* for launcher tests.

    Patches target the workflow step modules where the business logic now lives.
    ``hmp.Workspace`` and ``hmp.CatchmentDelineation`` are global (patching the module
    attribute affects all importers).
    """
    # Global module patches (affect all importers)
    monkeypatch.setattr("hydromodpy.workflow.steps.setup.hmp.Workspace", _DummyWorkspace)
    monkeypatch.setattr(
        "hydromodpy.workflow.steps.setup.hmp.CatchmentDelineation", _DummyGeographic
    )
    # Namespace-binding patches (step module)
    monkeypatch.setattr("hydromodpy.workflow.steps.setup.Domain", _DummyDomain)
    monkeypatch.setattr("hydromodpy.workflow.steps.setup.ensure_flow", _noop_ensure)
    monkeypatch.setattr("hydromodpy.workflow.steps.setup.ensure_transport", _noop_ensure)


def test_run_setup_uses_simulation_run_id(monkeypatch) -> None:
    _patch_launcher_deps(monkeypatch)

    cfg = SimpleNamespace(
        workspace=SimpleNamespace(),
        geographic=_standard_geographic_cfg(),
        domain=SimpleNamespace(),
        simulation=SimpleNamespace(run_id="my_run_id"),
    )
    run_state = WorkflowContext(
        cfg=cfg,
        config_path=Path("config.toml"),
        raw_toml={},
    )

    step_setup(run_state)

    assert run_state.setup.run_id == "my_run_id"


def test_run_setup_defaults_run_id_when_empty(monkeypatch) -> None:
    _patch_launcher_deps(monkeypatch)

    cfg = SimpleNamespace(
        workspace=SimpleNamespace(),
        geographic=_standard_geographic_cfg(),
        domain=SimpleNamespace(),
        simulation=SimpleNamespace(run_id=""),
    )
    run_state = WorkflowContext(
        cfg=cfg,
        config_path=Path("config.toml"),
        raw_toml={},
    )

    step_setup(run_state)

    assert run_state.setup.run_id == "config"  # derived from config.toml stem


def test_run_setup_stores_explicit_domain_geographic_context(monkeypatch) -> None:
    captured: dict[str, object] = {}
    _patch_launcher_deps(monkeypatch)

    def _fake_apply_catchment_zones_to_domain(*, domain, geographic, zone_id="catchment"):
        captured["domain"] = domain
        captured["geographic"] = geographic
        captured["zone_id"] = zone_id

    monkeypatch.setattr(
        "hydromodpy.workflow.steps.setup.apply_catchment_zones_to_domain",
        _fake_apply_catchment_zones_to_domain,
    )

    cfg = SimpleNamespace(
        workspace=SimpleNamespace(),
        geographic=_standard_geographic_cfg(),
        domain=SimpleNamespace(),
        simulation=SimpleNamespace(run_id="test"),
    )
    run_state = WorkflowContext(
        cfg=cfg,
        config_path=Path("config.toml"),
        raw_toml={},
    )

    step_setup(run_state)

    assert run_state.setup.domain_geographic is not None
    assert captured["domain"] is run_state.setup.domain
    assert captured["geographic"] is run_state.setup.domain_geographic
    assert captured["zone_id"] == "catchment"


def test_run_setup_builds_synthetic_geographic_when_requested(monkeypatch) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        "hydromodpy.workflow.steps.setup.hmp.Workspace",
        _DummyWorkspace,
    )
    monkeypatch.setattr(
        "hydromodpy.workflow.steps.setup.Domain",
        _DummyDomain,
    )

    def _unexpected_geographic(*args, **kwargs):
        raise AssertionError("standard geographic runtime should not be built")

    monkeypatch.setattr(
        "hydromodpy.workflow.steps.setup.hmp.CatchmentDelineation",
        _unexpected_geographic,
    )

    synthetic_runtime = _DummyGeographic(config=None, workspace=None)

    def _fake_build_synthetic_geographic(*, config, output_dir, workspace):
        captured["config"] = config
        captured["output_dir"] = output_dir
        captured["workspace"] = workspace
        return synthetic_runtime

    monkeypatch.setattr(
        "hydromodpy.workflow.steps.setup.build_synthetic_geographic",
        _fake_build_synthetic_geographic,
    )
    monkeypatch.setattr(
        "hydromodpy.workflow.steps.setup.apply_catchment_zones_to_domain",
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
    run_state = WorkflowContext(
        cfg=cfg,
        config_path=Path("config.toml"),
        raw_toml={},
    )

    monkeypatch.setattr(
        "hydromodpy.workflow.steps.setup.ensure_flow",
        _noop_ensure,
    )
    monkeypatch.setattr(
        "hydromodpy.workflow.steps.setup.ensure_transport",
        _noop_ensure,
    )

    step_setup(run_state)

    assert run_state.setup.geographic is synthetic_runtime
    assert captured["config"] is geographic_cfg.synthetic
    assert captured["workspace"] is run_state.setup.workspace
    assert (
        captured["output_dir"]
        == Path("workspace") / ".solver_scratch/_preprocessing" / "geographic"
    )


def test_process_launcher_rejects_embedded_mesh_catchment_batch_section() -> None:
    from hydromodpy.workflow.steps.mesh import resolve_optional_mesh_section

    with pytest.raises(ValueError, match="Embedded \\[mesh_catchment_batch\\] is not supported"):
        resolve_optional_mesh_section(
            {
                "mesh_catchment": {"constraints_mode": "rivers_only"},
                "mesh_catchment_batch": {
                    "enabled": True,
                    "outlets_table_path": "outlets.csv",
                },
            }
        )


def test_resolve_optional_mesh_input_resolves_relative_paths(tmp_path: Path) -> None:
    from hydromodpy.workflow.steps.mesh import resolve_optional_mesh_input

    config_path = tmp_path / "configs" / "simulation.toml"
    config_path.parent.mkdir(parents=True, exist_ok=True)

    actual = resolve_optional_mesh_input(
        {
            "mesh_input": {
                "mesh_path": "mesh/external_mesh.msh",
                "bundle_dir": "mesh/external_mesh_bundle",
            }
        },
        config_path,
    )

    assert actual == {
        "mesh_path": str((config_path.parent / "mesh/external_mesh.msh").resolve()),
        "bundle_dir": str((config_path.parent / "mesh/external_mesh_bundle").resolve()),
    }


def test_run_setup_does_not_declare_unused_geology_zone(monkeypatch) -> None:
    monkeypatch.setattr(
        "hydromodpy.workflow.steps.setup.hmp.Workspace",
        _DummyWorkspace,
    )
    monkeypatch.setattr(
        "hydromodpy.workflow.steps.setup.hmp.CatchmentDelineation",
        _DummyGeographic,
    )
    monkeypatch.setattr(
        "hydromodpy.workflow.steps.setup.Domain",
        _DummyDomain,
    )
    monkeypatch.setattr(
        "hydromodpy.workflow.steps.setup.apply_catchment_zones_to_domain",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        "hydromodpy.workflow.steps.setup.ensure_flow",
        lambda state: None,
    )
    monkeypatch.setattr(
        "hydromodpy.workflow.steps.setup.ensure_transport",
        lambda state: None,
    )

    cfg = SimpleNamespace(
        workspace=SimpleNamespace(),
        geographic=_standard_geographic_cfg(),
        domain=SimpleNamespace(zone_ids=[]),
        simulation=SimpleNamespace(run_id="test"),
    )
    run_state = WorkflowContext(
        cfg=cfg,
        config_path=Path("config.toml"),
        raw_toml={},
    )

    run_state.data_plan = SimpleNamespace(types=("geology",))

    step_setup(run_state)

    assert run_state.setup.domain.config.zone_ids == ["catchment"]


def test_run_setup_declares_requested_geology_support_id(monkeypatch) -> None:
    monkeypatch.setattr(
        "hydromodpy.workflow.steps.setup.hmp.Workspace",
        _DummyWorkspace,
    )
    monkeypatch.setattr(
        "hydromodpy.workflow.steps.setup.hmp.CatchmentDelineation",
        _DummyGeographic,
    )
    monkeypatch.setattr(
        "hydromodpy.workflow.steps.setup.Domain",
        _DummyDomain,
    )
    monkeypatch.setattr(
        "hydromodpy.workflow.steps.setup.apply_catchment_zones_to_domain",
        lambda **kwargs: None,
    )

    cfg = SimpleNamespace(
        workspace=SimpleNamespace(),
        geographic=_standard_geographic_cfg(),
        domain=SimpleNamespace(zone_ids=[]),
        simulation=SimpleNamespace(run_id="test"),
    )
    run_state = WorkflowContext(
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
        "hydromodpy.workflow.steps.setup.ensure_flow",
        _ensure_flow,
    )
    monkeypatch.setattr(
        "hydromodpy.workflow.steps.setup.ensure_transport",
        lambda state: None,
    )

    step_setup(
        run_state,
        requested_spatial_support_ids=("field_geology",),
        requested_domain_supports={
            "field_geology": SimpleNamespace(provider="geology"),
        },
    )

    assert run_state.setup.domain.config.zone_ids == ["catchment", "field_geology"]


def test_run_setup_rejects_heterogeneous_flow_when_support_is_undeclared(monkeypatch) -> None:
    monkeypatch.setattr(
        "hydromodpy.workflow.steps.setup.hmp.Workspace",
        _DummyWorkspace,
    )
    monkeypatch.setattr(
        "hydromodpy.workflow.steps.setup.hmp.CatchmentDelineation",
        _DummyGeographic,
    )
    monkeypatch.setattr(
        "hydromodpy.workflow.steps.setup.Domain",
        _DummyDomain,
    )
    monkeypatch.setattr(
        "hydromodpy.workflow.steps.setup.apply_catchment_zones_to_domain",
        lambda **kwargs: None,
    )

    cfg = SimpleNamespace(
        workspace=SimpleNamespace(),
        geographic=_standard_geographic_cfg(),
        domain=SimpleNamespace(zone_ids=[]),
        simulation=SimpleNamespace(run_id="test"),
    )
    run_state = WorkflowContext(
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
        "hydromodpy.workflow.steps.setup.ensure_flow",
        _ensure_flow,
    )
    monkeypatch.setattr(
        "hydromodpy.workflow.steps.setup.ensure_transport",
        lambda state: None,
    )

    with pytest.raises(ValueError, match="domain.supports"):
        step_setup(
            run_state,
            requested_spatial_support_ids=("field_geology",),
            requested_domain_supports={},
        )


def test_prepare_runtime_executes_embedded_mesh_phase_and_records_metrics(
    monkeypatch,
    hydromodpy_test_scratch_root: Path,
) -> None:
    """Verify prepare_runtime calls the mesh workflow with correct args."""
    from hydromodpy.spatial.mesh.config import parse_mesh_catchment_config_data
    from hydromodpy.workflow.pipeline import (
        execute_simulation,
        prepare_runtime,
    )

    workspace_root = _make_launcher_test_workspace_root(
        hydromodpy_test_scratch_root,
        prefix="mesh-sim-int-",
    )

    class _DummyRunWorkspace:
        def __init__(self, config) -> None:
            self.config = config
            self.project_root = Path(config.project_root).resolve()
            self.solver_scratch_folder = self.project_root / ".solver_scratch"

    class _DummyRunGeographic:
        def __init__(self, config, workspace) -> None:
            self.config = config
            self.workspace = workspace

        def get_domain_geographic_context(self):
            return SimpleNamespace(surface_topo=object(), river_mesh_trace="river-trace")

    class _DummyRunDomain:
        def __init__(self, config, surface_topo) -> None:
            self.config = config
            self.surface_topo = surface_topo

    class _DummyRuntimeLoader:
        def __init__(self, *a, **kw) -> None:
            pass

        def load_all(self, run_state) -> None:
            pass

    executed: dict[str, object] = {}
    captured_artifacts: dict[str, object] = {}
    captured_mesh: dict[str, object] = {}
    mesh_sentinel = object()

    class _DummySimulationRunner:
        def __init__(self, callbacks) -> None:
            executed["callbacks"] = callbacks

        def execute(self, plan, run_state) -> None:
            executed["run_state"] = run_state

    def _fake_mesh_workflow(**kwargs):
        captured_mesh.update(kwargs)
        return SimpleNamespace(
            summary={
                "constraints_mode": "rivers_only",
                "output_mesh": "workspace/results_stable/mesh/mesh_catchment.msh",
                "output_summary_json": "workspace/results_stable/mesh/mesh_catchment_summary.json",
            },
            mesh_planar=mesh_sentinel,
        )

    _patch_launcher_deps(monkeypatch)
    monkeypatch.setattr("hydromodpy.workflow.steps.setup.hmp.Workspace", _DummyRunWorkspace)
    monkeypatch.setattr(
        "hydromodpy.workflow.steps.setup.hmp.CatchmentDelineation", _DummyRunGeographic
    )
    monkeypatch.setattr("hydromodpy.workflow.steps.setup.Domain", _DummyRunDomain)
    monkeypatch.setattr(
        "hydromodpy.workflow.steps.data_loading._build_data_runtime_loader",
        lambda *a, **kw: _DummyRuntimeLoader(),
    )
    monkeypatch.setattr(
        "hydromodpy.workflow.steps.data_loading.apply_geology_to_domain", lambda **kw: None
    )
    monkeypatch.setattr(
        "hydromodpy.workflow.steps.data_loading.apply_oceanic_to_flow", lambda **kw: None
    )
    monkeypatch.setattr(
        "hydromodpy.workflow.steps.data_loading.apply_recharge_load_result_to_flow",
        lambda **kw: None,
    )
    monkeypatch.setattr("hydromodpy.workflow.steps.data_loading.ensure_flow", _noop_ensure)
    monkeypatch.setattr("hydromodpy.workflow.pipeline.SimulationRunner", _DummySimulationRunner)
    monkeypatch.setattr(
        "hydromodpy.spatial.mesh.runtime.run_single_mesh_catchment_workflow_with_runtime_artifacts",
        _fake_mesh_workflow,
    )
    monkeypatch.setattr(
        "hydromodpy.workflow.steps.mesh.load_planar_mesh",
        lambda path: (_ for _ in ()).throw(AssertionError("should keep mesh in memory")),
    )
    monkeypatch.setattr(
        "hydromodpy.workflow.pipeline.step_save_run_artifacts",
        lambda ctx, wall_seconds: captured_artifacts.update(
            {"mesh_summary": ctx.setup.mesh_summary}
        ),
    )

    cfg = SimpleNamespace(
        workspace=SimpleNamespace(project_root=workspace_root / "project"),
        geographic=SimpleNamespace(
            uses_synthetic_geographic=lambda: False, river_network=SimpleNamespace(enabled=False)
        ),
        domain=SimpleNamespace(zone_ids=[], supports={}),
        data=SimpleNamespace(types=()),
        flow=SimpleNamespace(active_bc=(), param={}),
        simulation=SimpleNamespace(
            run_id="mesh_run", results=SimpleNamespace(store=False, keep_solver_files=False)
        ),
    )
    mesh_section_data = parse_mesh_catchment_config_data({"constraints_mode": "rivers_only"})

    from hydromodpy.workflow.context import WorkflowContext

    ctx = WorkflowContext(cfg=cfg, config_path=Path("config.toml"), raw_toml={})
    ctx.setup.time_grid = SimpleNamespace(window=SimpleNamespace())
    ctx.data_plan = SimpleNamespace(types=(), inferred_types=(), reasons_for=lambda t: ())
    ctx.execution.simulation_plan = SimpleNamespace(runs=[])
    ctx.postprocess_runner = None

    try:
        prepare_runtime(
            ctx,
            mesh_section_data=mesh_section_data,
            constraints_mode="rivers_only",
        )
        execute_simulation(ctx)

        assert executed["run_state"] is ctx
        assert captured_mesh["constraints_mode"] == "rivers_only"
        assert captured_mesh["workspace"] is ctx.setup.workspace
        assert captured_mesh["domain_geographic"] is ctx.setup.domain_geographic
        assert ctx.setup.mesh_planar is mesh_sentinel
        assert ctx.setup.mesh_summary is not None
        assert (
            captured_artifacts["mesh_summary"]["output_mesh"]
            == "workspace/results_stable/mesh/mesh_catchment.msh"
        )
    finally:
        shutil.rmtree(workspace_root, ignore_errors=True)


def test_prepare_runtime_uses_external_mesh_input_and_skips_embedded_workflow(
    monkeypatch,
    hydromodpy_test_scratch_root: Path,
) -> None:
    """Verify prepare_runtime loads external mesh and skips embedded."""
    from hydromodpy.workflow.pipeline import (
        execute_simulation,
        prepare_runtime,
    )

    workspace_root = _make_launcher_test_workspace_root(
        hydromodpy_test_scratch_root,
        prefix="mesh-input-sim-int-",
    )
    external_mesh_path = workspace_root / "inputs" / "external_mesh.msh"

    class _DummyRunWorkspace:
        def __init__(self, config) -> None:
            self.config = config
            self.project_root = Path(config.project_root).resolve()
            self.solver_scratch_folder = self.project_root / ".solver_scratch"

    class _DummyRunGeographic:
        def __init__(self, config, workspace) -> None:
            self.config = config
            self.workspace = workspace

        def get_domain_geographic_context(self):
            return SimpleNamespace(surface_topo=object())

    class _DummyRunDomain:
        def __init__(self, config, surface_topo) -> None:
            self.config = config
            self.surface_topo = surface_topo

    class _DummyRuntimeLoader:
        def __init__(self, *a, **kw) -> None:
            pass

        def load_all(self, run_state) -> None:
            pass

    executed: dict[str, object] = {}
    mesh_load: dict[str, object] = {}
    mesh_sentinel = object()

    class _DummySimulationRunner:
        def __init__(self, callbacks) -> None:
            executed["callbacks"] = callbacks

        def execute(self, plan, run_state) -> None:
            executed["run_state"] = run_state

    def _fake_load_planar_mesh(path):
        mesh_load["path"] = Path(path).resolve()
        return mesh_sentinel

    _patch_launcher_deps(monkeypatch)
    monkeypatch.setattr("hydromodpy.workflow.steps.setup.hmp.Workspace", _DummyRunWorkspace)
    monkeypatch.setattr(
        "hydromodpy.workflow.steps.setup.hmp.CatchmentDelineation", _DummyRunGeographic
    )
    monkeypatch.setattr("hydromodpy.workflow.steps.setup.Domain", _DummyRunDomain)
    monkeypatch.setattr(
        "hydromodpy.workflow.steps.data_loading._build_data_runtime_loader",
        lambda *a, **kw: _DummyRuntimeLoader(),
    )
    monkeypatch.setattr(
        "hydromodpy.workflow.steps.data_loading.apply_geology_to_domain", lambda **kw: None
    )
    monkeypatch.setattr(
        "hydromodpy.workflow.steps.data_loading.apply_oceanic_to_flow", lambda **kw: None
    )
    monkeypatch.setattr(
        "hydromodpy.workflow.steps.data_loading.apply_recharge_load_result_to_flow",
        lambda **kw: None,
    )
    monkeypatch.setattr("hydromodpy.workflow.steps.data_loading.ensure_flow", _noop_ensure)
    monkeypatch.setattr("hydromodpy.workflow.pipeline.SimulationRunner", _DummySimulationRunner)
    monkeypatch.setattr(
        "hydromodpy.spatial.mesh.runtime.run_single_mesh_catchment_workflow_with_runtime_artifacts",
        lambda **kw: (_ for _ in ()).throw(AssertionError("embedded mesh workflow should not run")),
    )
    monkeypatch.setattr("hydromodpy.workflow.steps.mesh.load_planar_mesh", _fake_load_planar_mesh)

    cfg = SimpleNamespace(
        workspace=SimpleNamespace(project_root=workspace_root / "project"),
        geographic=SimpleNamespace(
            uses_synthetic_geographic=lambda: False, river_network=SimpleNamespace(enabled=False)
        ),
        domain=SimpleNamespace(zone_ids=[], supports={}),
        data=SimpleNamespace(types=()),
        flow=SimpleNamespace(active_bc=(), param={}),
        simulation=SimpleNamespace(
            run_id="mesh_input_run", results=SimpleNamespace(store=False, keep_solver_files=False)
        ),
    )
    external_mesh_input = {"mesh_path": str(external_mesh_path)}

    from hydromodpy.workflow.context import WorkflowContext

    ctx = WorkflowContext(cfg=cfg, config_path=Path("config.toml"), raw_toml={})
    ctx.setup.time_grid = SimpleNamespace(window=SimpleNamespace())
    ctx.data_plan = SimpleNamespace(types=(), inferred_types=(), reasons_for=lambda t: ())
    ctx.execution.simulation_plan = SimpleNamespace(runs=[])
    ctx.postprocess_runner = None

    try:
        prepare_runtime(ctx, external_mesh_input=external_mesh_input)
        execute_simulation(ctx)

        assert executed["run_state"] is ctx
        assert ctx.setup.mesh_bundle is None
        assert ctx.setup.mesh_planar is mesh_sentinel
        assert ctx.setup.mesh_summary is not None
        assert ctx.setup.mesh_summary["mesh_source"] == "external_input"
        assert ctx.setup.mesh_summary["output_mesh"] == str(external_mesh_path)
        assert mesh_load["path"] == external_mesh_path
    finally:
        shutil.rmtree(workspace_root, ignore_errors=True)


def test_run_mesh_input_phase_loads_bundle_and_infers_mesh_path(monkeypatch) -> None:
    run_state = WorkflowContext(
        cfg=SimpleNamespace(),
        config_path=Path("config.toml"),
        raw_toml={},
    )
    mesh_sentinel = object()
    bundle_path = Path("C:/tmp/external_mesh_bundle")
    bundle = SimpleNamespace(mesh_path=bundle_path / "mesh_2d.msh")

    monkeypatch.setattr(
        "hydromodpy.workflow.steps.mesh.load_catchment_mesh_bundle",
        lambda path: bundle,
    )
    monkeypatch.setattr(
        "hydromodpy.workflow.steps.mesh.load_planar_mesh",
        lambda path: mesh_sentinel,
    )

    step_mesh_input(
        run_state,
        external_mesh_input={
            "mesh_path": "",
            "bundle_dir": str(bundle_path),
        },
    )

    assert run_state.setup.mesh_bundle is bundle
    assert run_state.setup.mesh_planar is mesh_sentinel
    assert run_state.setup.mesh_summary == {
        "mesh_source": "external_input",
        "output_exchange_bundle_dir": str(bundle_path),
        "output_mesh": str(bundle.mesh_path),
    }
