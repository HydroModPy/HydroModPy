"""Unit tests for workflow setup step run_id and domain support handling."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from hydromodpy.core.exceptions import ConfigError
from hydromodpy.core.state.paths import preprocessing_dir
from hydromodpy.core.state.run_state import WorkflowContext
from hydromodpy.spatial.domain.domain_config import DomainConfig
from hydromodpy.workflow.steps.setup import step_setup

from ._launcher_run_id_builders import (
    _DummyDomain,
    _DummyGeographic,
    _DummyWorkspace,
    _noop_ensure,
    _patch_launcher_deps,
    _standard_geographic_cfg,
)

PREPROCESSING_DIR = preprocessing_dir(Path())


def test_run_setup_uses_simulation_name(monkeypatch) -> None:
    _patch_launcher_deps(monkeypatch)

    cfg = SimpleNamespace(
        workspace=SimpleNamespace(),
        geographic=_standard_geographic_cfg(),
        domain=DomainConfig(),
        simulation=SimpleNamespace(name="my_run_id"),
    )
    run_state = WorkflowContext(
        cfg=cfg,
        config_path=Path("config.toml"),
        raw_toml={},
    )

    step_setup(run_state)

    assert run_state.setup.run_id == "my_run_id"


def test_run_setup_defaults_run_id_when_name_empty(monkeypatch) -> None:
    _patch_launcher_deps(monkeypatch)

    cfg = SimpleNamespace(
        workspace=SimpleNamespace(),
        geographic=_standard_geographic_cfg(),
        domain=DomainConfig(),
        simulation=SimpleNamespace(name=""),
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
        domain=DomainConfig(),
        simulation=SimpleNamespace(name="test"),
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
        "hydromodpy.workflow.steps.setup.Workspace",
        _DummyWorkspace,
    )
    monkeypatch.setattr(
        "hydromodpy.spatial.domain.build.Domain",
        _DummyDomain,
    )

    def _unexpected_geographic(*args, **kwargs):
        raise AssertionError("standard geographic runtime should not be built")

    monkeypatch.setattr(
        "hydromodpy.workflow.steps.setup.CatchmentDelineation",
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
        domain=DomainConfig(),
        simulation=SimpleNamespace(name="test"),
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
    assert captured["output_dir"] == Path("workspace") / PREPROCESSING_DIR / "geographic"


def test_run_setup_declares_the_binder_zone_ids(monkeypatch) -> None:
    """apply_geology_to_domain writes under a fixed zone id, so the runtime arms it."""
    monkeypatch.setattr(
        "hydromodpy.workflow.steps.setup.Workspace",
        _DummyWorkspace,
    )
    monkeypatch.setattr(
        "hydromodpy.workflow.steps.setup.CatchmentDelineation",
        _DummyGeographic,
    )
    monkeypatch.setattr(
        "hydromodpy.spatial.domain.build.Domain",
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
        domain=DomainConfig(),
        simulation=SimpleNamespace(name="test"),
    )
    run_state = WorkflowContext(
        cfg=cfg,
        config_path=Path("config.toml"),
        raw_toml={},
    )

    run_state.data_plan = SimpleNamespace(types=("geology",))

    step_setup(run_state)

    assert run_state.setup.domain.config.zone_ids == ["catchment", "geology"]


def test_run_setup_declares_requested_geology_support_id(monkeypatch) -> None:
    monkeypatch.setattr(
        "hydromodpy.workflow.steps.setup.Workspace",
        _DummyWorkspace,
    )
    monkeypatch.setattr(
        "hydromodpy.workflow.steps.setup.CatchmentDelineation",
        _DummyGeographic,
    )
    monkeypatch.setattr(
        "hydromodpy.spatial.domain.build.Domain",
        _DummyDomain,
    )
    monkeypatch.setattr(
        "hydromodpy.workflow.steps.setup.apply_catchment_zones_to_domain",
        lambda **kwargs: None,
    )

    cfg = SimpleNamespace(
        workspace=SimpleNamespace(),
        geographic=_standard_geographic_cfg(),
        domain=DomainConfig(),
        simulation=SimpleNamespace(name="test"),
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
            "field_geology": SimpleNamespace(kind="geology"),
        },
    )

    assert run_state.setup.domain.config.zone_ids == ["catchment", "geology", "field_geology"]


def test_run_setup_rejects_heterogeneous_flow_when_support_is_undeclared(monkeypatch) -> None:
    monkeypatch.setattr(
        "hydromodpy.workflow.steps.setup.Workspace",
        _DummyWorkspace,
    )
    monkeypatch.setattr(
        "hydromodpy.workflow.steps.setup.CatchmentDelineation",
        _DummyGeographic,
    )
    monkeypatch.setattr(
        "hydromodpy.spatial.domain.build.Domain",
        _DummyDomain,
    )
    monkeypatch.setattr(
        "hydromodpy.workflow.steps.setup.apply_catchment_zones_to_domain",
        lambda **kwargs: None,
    )

    cfg = SimpleNamespace(
        workspace=SimpleNamespace(),
        geographic=_standard_geographic_cfg(),
        domain=DomainConfig(),
        simulation=SimpleNamespace(name="test"),
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

    with pytest.raises(ConfigError, match="domain.supports"):
        step_setup(
            run_state,
            requested_spatial_support_ids=("field_geology",),
            requested_domain_supports={},
        )
