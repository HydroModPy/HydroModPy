"""Shared builders and fakes for launcher run_id setup/runtime tests."""

from __future__ import annotations

import tempfile
from pathlib import Path
from types import SimpleNamespace

from hydromodpy.core.state.paths import scratch_dir_for


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
        self.solver_scratch_folder = scratch_dir_for(self.project_root)


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
    """
    monkeypatch.setattr("hydromodpy.workflow.steps.setup.Workspace", _DummyWorkspace)
    monkeypatch.setattr("hydromodpy.workflow.steps.setup.CatchmentDelineation", _DummyGeographic)
    monkeypatch.setattr("hydromodpy.workflow.steps.setup.Domain", _DummyDomain)
    monkeypatch.setattr("hydromodpy.workflow.steps.setup.ensure_flow", _noop_ensure)
    monkeypatch.setattr("hydromodpy.workflow.steps.setup.ensure_transport", _noop_ensure)
