"""Auto-registration of workspaces in the global index on workflow setup.

The setup step must register the workspace ``project_root`` in the
machine-wide ``GlobalIndex`` so subsequent ``hmp index search`` calls
federate across every workspace that ever booted on the machine.

Failures are best-effort: they must never raise. We assert silent recovery
when the index is unreachable (read-only state dir) and idempotent
behaviour on duplicate registrations (``UNIQUE (workspace_uri)``).
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from hydromodpy.core.state.global_index import GlobalIndex, auto_register_workspace
from hydromodpy.core.state.paths import scratch_dir_for
from hydromodpy.core.state.run_state import WorkflowContext


class _DummyWorkspace:
    def __init__(self, config: object) -> None:
        self.config = config
        self.project_root = Path(getattr(config, "project_root", "workspace"))
        self.project_root.mkdir(parents=True, exist_ok=True)
        self.solver_scratch_folder = scratch_dir_for(self.project_root)
        self.catch_name = self.project_root.name


class _DummyGeographic:
    def __init__(self, *_args: object, **_kwargs: object) -> None:
        pass

    def get_domain_surface_topo(self) -> SimpleNamespace:
        return SimpleNamespace(support=object())


def _noop_ensure(_state: object) -> None:
    """Replacement for ensure_flow / ensure_transport in tests."""


def _patch_setup_deps(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch heavyweight dependencies of ``run_setup`` for fast tests."""
    monkeypatch.setattr("hydromodpy.workflow.steps.setup.Workspace", _DummyWorkspace)
    monkeypatch.setattr(
        "hydromodpy.workflow.steps.setup.CatchmentDelineation",
        _DummyGeographic,
    )
    monkeypatch.setattr(
        "hydromodpy.workflow.steps.setup.Domain",
        lambda **kwargs: SimpleNamespace(**kwargs, zones={}),
    )
    monkeypatch.setattr(
        "hydromodpy.workflow.steps.setup.coerce_geographic_derived_features",
        lambda *, geographic: SimpleNamespace(
            surface_topo=SimpleNamespace(support=object()),
            to_domain_geographic_context=lambda: SimpleNamespace(),
        ),
    )
    monkeypatch.setattr(
        "hydromodpy.workflow.steps.setup.apply_catchment_zones_to_domain",
        lambda **kwargs: None,
    )
    monkeypatch.setattr("hydromodpy.workflow.steps.setup.ensure_flow", _noop_ensure)
    monkeypatch.setattr("hydromodpy.workflow.steps.setup.ensure_transport", _noop_ensure)
    monkeypatch.setattr(
        "hydromodpy.workflow.steps.setup.resolve_dem_init_path",
        lambda cfg, run_state: None,
    )


def test_auto_register_workspace_persists_uri(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A first call records the workspace_uri exactly once."""
    monkeypatch.setenv("HMP_STATE_HOME", str(tmp_path / "state"))

    workspace_root = tmp_path / "ws_a" / "projects" / "demo"
    workspace_root.mkdir(parents=True)

    workspace_id = auto_register_workspace(workspace_root, label="demo")
    assert workspace_id is not None

    with GlobalIndex() as index:
        records = index.list_workspaces()

    assert len(records) == 1
    assert records[0].workspace_uri == str(workspace_root)
    assert records[0].label == "demo"


def test_auto_register_workspace_is_idempotent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Duplicate registrations are silently absorbed by the UNIQUE constraint."""
    monkeypatch.setenv("HMP_STATE_HOME", str(tmp_path / "state"))

    workspace_root = tmp_path / "ws_b"
    workspace_root.mkdir()

    first_id = auto_register_workspace(workspace_root, label="ws_b")
    second_id = auto_register_workspace(workspace_root, label="ws_b")

    assert first_id is not None
    assert second_id is None

    with GlobalIndex() as index:
        records = index.list_workspaces()
    assert len(records) == 1
    assert records[0].workspace_id == first_id


def test_auto_register_workspace_skips_federation_refresh(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Auto-registration must not attach catalogs during concurrent runs."""
    from hydromodpy.core.state import global_index as gi_mod

    monkeypatch.setenv("HMP_STATE_HOME", str(tmp_path / "state"))

    def _fail_refresh(_self: object) -> None:
        raise AssertionError("auto-registration should not refresh federation")

    monkeypatch.setattr(gi_mod.GlobalIndex, "refresh_federation", _fail_refresh)

    workspace_root = tmp_path / "ws_no_refresh"
    workspace_root.mkdir()

    workspace_id = auto_register_workspace(workspace_root, label="no-refresh")

    assert workspace_id is not None
    with GlobalIndex(refresh_federation=False) as index:
        records = index.list_workspaces()
    assert len(records) == 1
    assert records[0].workspace_id == workspace_id


def test_auto_register_workspace_swallows_errors(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Hook never raises: a broken index path is logged at DEBUG and returns None."""
    from hydromodpy.core.state import global_index as gi_mod

    class _BrokenIndex:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            raise RuntimeError("simulated index failure")

    monkeypatch.setattr(gi_mod, "GlobalIndex", _BrokenIndex)

    result = auto_register_workspace(tmp_path / "ws_broken")
    assert result is None


def test_auto_register_workspace_respects_env_opt_out(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Validation subprocesses can disable machine-wide index writes."""
    monkeypatch.setenv("HMP_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("HMP_AUTO_REGISTER_WORKSPACE", "0")

    workspace_root = tmp_path / "ws_disabled"
    workspace_root.mkdir()

    result = auto_register_workspace(workspace_root, label="disabled")
    assert result is None

    with GlobalIndex() as index:
        assert index.list_workspaces() == []


def test_step_setup_registers_workspace_in_global_index(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """End-to-end: running the setup step adds the workspace URI to the index."""
    monkeypatch.setenv("HMP_STATE_HOME", str(tmp_path / "state"))
    _patch_setup_deps(monkeypatch)

    from hydromodpy.workflow.steps.setup import step_setup

    project_root = tmp_path / "ws_setup" / "projects" / "demo"

    cfg = SimpleNamespace(
        workspace=SimpleNamespace(project_root=project_root),
        geographic=SimpleNamespace(uses_synthetic_geographic=lambda: False),
        domain=SimpleNamespace(zone_ids=[]),
        simulation=SimpleNamespace(name="demo_run", run_id="test", rng_seed=None),
    )
    run_state = WorkflowContext(
        cfg=cfg,
        config_path=tmp_path / "config.toml",
        raw_toml={},
    )

    step_setup(run_state)

    with GlobalIndex() as index:
        records = index.list_workspaces()
    uris = {record.workspace_uri for record in records}
    assert str(project_root) in uris
