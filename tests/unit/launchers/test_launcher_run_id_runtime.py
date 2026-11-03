"""Unit tests for the mesh phase of prepare_runtime."""

from __future__ import annotations

import shutil
from pathlib import Path
from types import SimpleNamespace

from hydromodpy.core.state.paths import scratch_dir_for
from hydromodpy.core.state.run_state import WorkflowContext
from hydromodpy.spatial.domain.domain_config import DomainConfig

from ._launcher_run_id_builders import (
    _make_launcher_test_workspace_root,
    _noop_ensure,
    _patch_launcher_deps,
)


def test_prepare_runtime_builds_the_cell_mesh_after_the_data_are_loaded(
    monkeypatch,
    hydromodpy_test_scratch_root: Path,
) -> None:
    """The mesh step gets the context once the geographic runtime and the data are bound."""
    from hydromodpy.workflow.orchestrator import prepare_runtime

    workspace_root = _make_launcher_test_workspace_root(
        hydromodpy_test_scratch_root,
        prefix="mesh-sim-int-",
    )

    class _DummyRunWorkspace:
        def __init__(self, config) -> None:
            self.config = config
            self.project_root = Path(config.project_root).resolve()
            self.solver_scratch_folder = scratch_dir_for(self.project_root)

    class _DummyRunGeographic:
        def __init__(
            self, config, workspace, *, reuse_existing_outputs=None, network_map_path=None
        ) -> None:
            self.config = config
            self.workspace = workspace
            self.reuse_existing_outputs = reuse_existing_outputs

        def get_domain_geographic_context(self):
            return SimpleNamespace(surface_topo=object())

        def get_geographic_derived_features(self):
            return SimpleNamespace(
                surface_topo=object(),
                rivers=SimpleNamespace(river_mesh_trace="river-trace"),
                to_domain_geographic_context=self.get_domain_geographic_context,
            )

    class _DummyRunDomain:
        def __init__(
            self,
            config,
            surface_topo,
            substratum_source=None,
            layer_base_sources=None,
            active_cells=None,
        ) -> None:
            self.config = config
            self.surface_topo = surface_topo

    class _DummyRuntimeLoader:
        def __init__(self, *a, **kw) -> None:
            pass

        def load_all(self, run_state) -> None:
            pass

    seen: dict[str, object] = {}
    mesh_sentinel = object()

    def _fake_step_mesh(ctx, *, resume=False):
        seen["ctx"] = ctx
        seen["domain_geographic"] = ctx.setup.domain_geographic
        ctx.setup.cell_mesh = mesh_sentinel

    _patch_launcher_deps(monkeypatch)
    monkeypatch.setattr("hydromodpy.workflow.steps.setup.WorkspaceLayout", _DummyRunWorkspace)
    monkeypatch.setattr("hydromodpy.workflow.steps.setup.CatchmentDelineation", _DummyRunGeographic)
    monkeypatch.setattr("hydromodpy.spatial.domain.build.Domain", _DummyRunDomain)
    monkeypatch.setattr(
        "hydromodpy.workflow.steps.data._build_data_runtime_loader",
        lambda *a, **kw: _DummyRuntimeLoader(),
    )
    monkeypatch.setattr("hydromodpy.workflow.steps.data.apply_geology_to_domain", lambda **kw: None)
    monkeypatch.setattr("hydromodpy.workflow.steps.data.apply_oceanic_to_flow", lambda **kw: None)
    monkeypatch.setattr(
        "hydromodpy.workflow.steps.data.apply_recharge_load_result_to_flow",
        lambda **kw: None,
    )
    monkeypatch.setattr("hydromodpy.workflow.steps.data.ensure_flow", _noop_ensure)
    monkeypatch.setattr("hydromodpy.workflow.steps.mesh.step_mesh", _fake_step_mesh)

    cfg = SimpleNamespace(
        workspace=SimpleNamespace(project_root=workspace_root / "project"),
        geographic=SimpleNamespace(
            uses_synthetic_geographic=lambda: False, river_network=SimpleNamespace(enabled=False)
        ),
        domain=DomainConfig(),
        data=SimpleNamespace(types=()),
        flow=SimpleNamespace(active_bc=(), param={}),
        simulation=SimpleNamespace(
            name="mesh_run",
            results=SimpleNamespace(
                persistence=SimpleNamespace(save_catalog=False),
                keep_solver_files=False,
            ),
        ),
    )
    ctx = WorkflowContext(cfg=cfg, config_path=Path("config.toml"), raw_toml={})
    ctx.setup.time_grid = SimpleNamespace(window=SimpleNamespace())
    ctx.data_plan = SimpleNamespace(types=(), inferred_types=(), reasons_for=lambda t: ())
    ctx.execution.simulation_plan = SimpleNamespace(runs=[])

    try:
        prepare_runtime(ctx)

        assert seen["ctx"] is ctx
        assert seen["domain_geographic"] is ctx.setup.domain_geographic
        assert ctx.setup.domain_geographic is not None
        assert ctx.setup.cell_mesh is mesh_sentinel
    finally:
        shutil.rmtree(workspace_root, ignore_errors=True)
