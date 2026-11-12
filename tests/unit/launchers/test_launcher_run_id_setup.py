"""The workflow setup step: the run id and the declared zone supports of the domain.

The workspace, the catchment delineation and the domain are replaced by small
stand-ins, so only the step's own logic runs."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from hydromodpy.core.exceptions import ConfigError
from hydromodpy.core.state.run_state import WorkflowContext
from hydromodpy.core.state.scratch import preprocessing_dir, scratch_dir_for
from hydromodpy.model.domain.domain_config import DomainConfig
from hydromodpy.workflow.steps.setup import step_setup


class DummyWorkspace:
    def __init__(self, config) -> None:
        self.config = config
        self.project_root = Path("workspace")
        self.solver_scratch_folder = scratch_dir_for(self.project_root)


class DummyGeographic:
    def __init__(self, config, workspace, **_ignored) -> None:
        self.config = config
        self.workspace = workspace

    def get_domain_surface_topo(self):
        return SimpleNamespace(support=object())

    def get_domain_geographic_context(self):
        return SimpleNamespace(
            surface_topo=self.get_domain_surface_topo(),
            watershed_shp="watershed.shp",
            catchment_area_km2=1.0,
            kind="from_outlet_coord",
            x_outlet=1.0,
            y_outlet=2.0,
            watershed_box_buff_dem="watershed_box_buff_dem.tif",
            box_buff_shp="watershed_box_buff.shp",
            zone_kind="catchment",
        )


class DummyDomain:
    def __init__(self, config, surface_topo, **_ignored) -> None:
        self.config = config
        self.surface_topo = surface_topo


def no_flow(state) -> None:
    pass


def geology_flow(state) -> None:
    state.setup.flow = SimpleNamespace(
        parameters={"K": SimpleNamespace(is_heterogeneous=True, field_spatial_id="field_geology")}
    )


def skip_zones(monkeypatch) -> None:
    monkeypatch.setattr(
        "hydromodpy.workflow.steps.setup.apply_catchment_zones_to_domain", lambda **kwargs: None
    )


def a_state(name: str) -> WorkflowContext:
    cfg = SimpleNamespace(
        workspace=SimpleNamespace(),
        geographic=SimpleNamespace(uses_synthetic_geographic=lambda: False),
        domain=DomainConfig(),
        simulation=SimpleNamespace(name=name),
    )
    return WorkflowContext(cfg=cfg, config_path=Path("config.toml"), raw_toml={})


def patch_setup(monkeypatch, ensure_flow) -> None:
    # build_domain is patched one module deeper than the step, because it holds the
    # copy of the declared section the tests assert on.
    monkeypatch.setattr("hydromodpy.workflow.steps.setup.WorkspaceLayout", DummyWorkspace)
    monkeypatch.setattr("hydromodpy.workflow.steps.setup.CatchmentDelineation", DummyGeographic)
    monkeypatch.setattr("hydromodpy.model.domain.build.Domain", DummyDomain)
    monkeypatch.setattr("hydromodpy.workflow.steps.setup.ensure_flow", ensure_flow)


def test_run_id_from_config_stem(monkeypatch) -> None:
    patch_setup(monkeypatch, no_flow)
    state = a_state(name="")

    step_setup(state)

    assert state.setup.run_id == "config"


def test_geology_support_declared(monkeypatch) -> None:
    patch_setup(monkeypatch, geology_flow)
    skip_zones(monkeypatch)
    state = a_state(name="test")

    step_setup(
        state,
        requested_spatial_support_ids=("field_geology",),
        requested_domain_supports={"field_geology": SimpleNamespace(kind="geology")},
    )

    assert state.setup.domain.config.zone_ids == ["catchment", "geology", "field_geology"]


def test_refusal_without_declared_support(monkeypatch) -> None:
    patch_setup(monkeypatch, geology_flow)
    skip_zones(monkeypatch)

    with pytest.raises(ConfigError, match="domain.supports"):
        step_setup(
            a_state(name="test"),
            requested_spatial_support_ids=("field_geology",),
            requested_domain_supports={},
        )


def test_preprocessing_under_scratch() -> None:
    root = Path("workspace")

    assert preprocessing_dir(root).parent == scratch_dir_for(root)
