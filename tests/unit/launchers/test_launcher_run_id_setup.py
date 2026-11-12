"""Unit tests for workflow setup step run_id and domain support handling."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from hydromodpy.core.exceptions import ConfigError
from hydromodpy.core.state.run_state import WorkflowContext
from hydromodpy.core.state.scratch import preprocessing_dir
from hydromodpy.model.domain.domain_config import DomainConfig
from hydromodpy.workflow.steps.setup import step_setup

from ._launcher_run_id_builders import (
    _DummyDomain,
    _DummyGeographic,
    _DummyWorkspace,
    _patch_launcher_deps,
    _standard_geographic_cfg,
)

PREPROCESSING_DIR = preprocessing_dir(Path())


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


def test_run_setup_declares_requested_geology_support_id(monkeypatch) -> None:
    monkeypatch.setattr(
        "hydromodpy.workflow.steps.setup.WorkspaceLayout",
        _DummyWorkspace,
    )
    monkeypatch.setattr(
        "hydromodpy.workflow.steps.setup.CatchmentDelineation",
        _DummyGeographic,
    )
    monkeypatch.setattr(
        "hydromodpy.model.domain.build.Domain",
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
        "hydromodpy.workflow.steps.setup.WorkspaceLayout",
        _DummyWorkspace,
    )
    monkeypatch.setattr(
        "hydromodpy.workflow.steps.setup.CatchmentDelineation",
        _DummyGeographic,
    )
    monkeypatch.setattr(
        "hydromodpy.model.domain.build.Domain",
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

    with pytest.raises(ConfigError, match="domain.supports"):
        step_setup(
            run_state,
            requested_spatial_support_ids=("field_geology",),
            requested_domain_supports={},
        )
