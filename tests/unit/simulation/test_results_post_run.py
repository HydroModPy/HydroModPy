"""Tests for simulation/results/post_run.py - post-run hook."""

from __future__ import annotations

import shutil
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

import hydromodpy.simulation.extraction.post_run as post_run_module
from hydromodpy.core.config_kit.persistence import PersistenceConfig
from hydromodpy.core.state.run_state import RunState
from hydromodpy.results.catalog import Catalog
from hydromodpy.simulation.extraction.post_run import post_run_results
from hydromodpy.simulation.planning.plan import ProcessRun, RunContext, SimulationPlan
from hydromodpy.simulation.planning.results_config import ResultsConfig
from hydromodpy.solver.base.solver_config import SolverConfig
from hydromodpy.solver.modflow_nwt.nwt import ModflowConfig
from tests._helpers.fixtures_catalog import simulation_catalog


@pytest.fixture
def catalog(tmp_path):
    with simulation_catalog(tmp_path / "workspace") as cat:
        yield cat


def _build_run_context(
    *,
    solver_name: str,
    process_type: str = "flow",
    solver_output_dir: Path | None = None,
) -> RunContext:
    """Build a minimal RunContext for post_run_results tests.

    The context carries the solver output directory for the
    ``adapter.cleanup(ctx)`` path, plus the ``cfg`` the extraction phase reads
    to hand the configured dry-cell sentinels to the extractor.
    """
    run = ProcessRun(
        id=f"{process_type}_main::{solver_name}",
        process_id=f"{process_type}_main",
        process_type=process_type,
        solver=solver_name,
    )
    plan = SimulationPlan(name="test", description="test", runs=(run,))
    state = RunState(
        cfg=SimpleNamespace(modflownwt=ModflowConfig(), solver=SolverConfig()),
    )
    return RunContext(plan=plan, run=run, state=state, output_dir=solver_output_dir)


class _FakeExtractor:
    category = "distributed"

    def __init__(self) -> None:
        self.extract_calls: list[dict] = []
        self.derive_calls: list[dict] = []

    def extract(self, sim_id, solver_output_dir, store, **kwargs) -> None:
        self.extract_calls.append(
            {
                "sim_id": sim_id,
                "solver_output_dir": Path(solver_output_dir),
                "kwargs": dict(kwargs),
            }
        )

    def derive(self, sim_id, store, derived_flags) -> None:
        self.derive_calls.append({"sim_id": sim_id, "derived_flags": dict(derived_flags)})


class _FakeLumpedExtractor(_FakeExtractor):
    category = "lumped"


class _FakeAdapter:
    def __init__(self) -> None:
        self.cleanup_calls: list[RunContext] = []

    def cleanup(self, ctx: RunContext) -> None:
        self.cleanup_calls.append(ctx)
        if ctx.output_dir is not None:
            shutil.rmtree(ctx.output_dir)


class _FakeProvider:
    def __init__(self, *, extractor: _FakeExtractor | None = None) -> None:
        self.extractor = extractor
        self.adapter = _FakeAdapter()

    def get_extractor_instance(self, process_type: str, solver_name: str):
        if solver_name == "fake_solver":
            return self.extractor
        return None

    def get_solver_adapter(self, process_type: str, solver_name: str):
        if process_type == "flow" and solver_name == "fake_solver":
            return self.adapter
        raise KeyError((process_type, solver_name))


def _install_post_run_stubs(
    monkeypatch, *, extractor: _FakeExtractor | None = None
) -> _FakeProvider:
    provider = _FakeProvider(extractor=extractor)
    monkeypatch.setattr(post_run_module, "get_solver_registry_provider", lambda: provider)
    monkeypatch.setattr(
        "hydromodpy.simulation.extraction.derivation.catchment_aggregation."
        "aggregate_catchment_timeseries",
        lambda sim_id, store: None,
    )
    return provider


class TestPostRunResults:
    def test_store_disabled_noop(self, catalog, tmp_path):
        sid = str(uuid4())
        catalog.register_simulation(sid, project="test", solver="modflow_nwt")
        config = ResultsConfig(persistence=PersistenceConfig(save_catalog=False))
        ctx = _build_run_context(solver_name="modflow_nwt", solver_output_dir=tmp_path)
        # Should return without doing anything
        post_run_results(
            ctx=ctx,
            sim_id=sid,
            results_config=config,
            store=catalog,
        )

    def test_unknown_solver_raises(self, catalog, tmp_path, monkeypatch):
        sid = str(uuid4())
        catalog.register_simulation(sid, project="test", solver="modflow_nwt")
        config = ResultsConfig()
        # Trigger the "no extractor" path via a run-context solver name the
        # _FakeProvider stub does not recognise.
        ctx = _build_run_context(solver_name="custom_solver", solver_output_dir=tmp_path)
        _install_post_run_stubs(monkeypatch)
        with pytest.raises(RuntimeError, match="No output adapter"):
            post_run_results(
                ctx=ctx,
                sim_id=sid,
                results_config=config,
                store=catalog,
            )

    def test_no_output_dir_raises(self, catalog, monkeypatch):
        sid = str(uuid4())
        catalog.register_simulation(sid, project="test", solver="modflow_nwt")
        config = ResultsConfig()
        ctx = _build_run_context(solver_name="fake_solver", solver_output_dir=None)
        _install_post_run_stubs(monkeypatch, extractor=_FakeExtractor())
        with pytest.raises(FileNotFoundError, match="Solver output directory is missing"):
            post_run_results(
                ctx=ctx,
                sim_id=sid,
                results_config=config,
                store=catalog,
            )

    def test_cleanup_when_keep_false(self, catalog, tmp_path, monkeypatch):
        sid = str(uuid4())
        catalog.register_simulation(sid, project="test", solver="modflow_nwt")

        solver_dir = tmp_path / "solver_out"
        solver_dir.mkdir()
        (solver_dir / "model.hds").write_text("head data")

        config = ResultsConfig(keep_solver_files=False)
        ctx = _build_run_context(solver_name="fake_solver", solver_output_dir=solver_dir)
        provider = _install_post_run_stubs(monkeypatch, extractor=_FakeExtractor())
        post_run_results(
            ctx=ctx,
            sim_id=sid,
            results_config=config,
            store=catalog,
        )
        assert not solver_dir.exists()
        assert provider.adapter.cleanup_calls == [ctx]

    def test_keep_solver_files(self, catalog, tmp_path, monkeypatch):
        sid = str(uuid4())
        catalog.register_simulation(sid, project="test", solver="modflow_nwt")

        solver_dir = tmp_path / "solver_out"
        solver_dir.mkdir()
        (solver_dir / "model.hds").write_text("head data")

        config = ResultsConfig(keep_solver_files=True)
        ctx = _build_run_context(solver_name="fake_solver", solver_output_dir=solver_dir)
        provider = _install_post_run_stubs(monkeypatch, extractor=_FakeExtractor())
        post_run_results(
            ctx=ctx,
            sim_id=sid,
            results_config=config,
            store=catalog,
        )
        assert (solver_dir / "model.hds").exists()
        assert provider.adapter.cleanup_calls == []

    def test_lumped_extractor_skips_catchment_aggregation(self, catalog, tmp_path, monkeypatch):
        sid = str(uuid4())
        catalog.register_simulation(sid, project="test", solver="gr4j")

        solver_dir = tmp_path / "solver_out"
        solver_dir.mkdir()

        provider = _FakeProvider(extractor=_FakeLumpedExtractor())
        monkeypatch.setattr(post_run_module, "get_solver_registry_provider", lambda: provider)

        def _fail_aggregation(sim_id, store):
            raise AssertionError("lumped extractors must not aggregate spatial fields")

        monkeypatch.setattr(
            "hydromodpy.simulation.extraction.derivation.catchment_aggregation."
            "aggregate_catchment_timeseries",
            _fail_aggregation,
        )

        config = ResultsConfig(keep_solver_files=True)
        ctx = _build_run_context(solver_name="fake_solver", solver_output_dir=solver_dir)
        post_run_results(
            ctx=ctx,
            sim_id=sid,
            results_config=config,
            store=catalog,
        )


class _RecordingStore:
    """Fake store that records the ExportSpecs ``_auto_export`` builds, without exporting."""

    def __init__(self, project_path: Path):
        self.project_path = project_path
        self.specs: list = []

    def export(self, sim_id, spec):
        self.specs.append(spec)
        return spec.dest

    def record_export(self, sim_id, *, kind, path):
        pass


class TestAutoExportGeopackageWiring:
    """``export.geopackage`` must build one .gpkg spec per variable, one timestep, like shapefile."""

    def test_one_gpkg_spec_per_variable(self, tmp_path):
        from hydromodpy.simulation.planning.export_config import ExportConfig

        store = _RecordingStore(tmp_path)
        export = ExportConfig(geopackage=True, variables=["head", "seepage_mask"], time="last")

        post_run_module._auto_export(
            "sim-1",
            store,
            export,
            export_label="run1",
        )

        dests = [Path(spec.dest).name for spec in store.specs]
        assert dests == ["head_last.gpkg", "seepage_mask_last.gpkg"]
        assert all(spec.time == "last" for spec in store.specs)

    def test_geopackage_off_writes_nothing(self, tmp_path):
        from hydromodpy.simulation.planning.export_config import ExportConfig

        store = _RecordingStore(tmp_path)
        export = ExportConfig(shapefile=True, variables=["head"], time="last")

        post_run_module._auto_export("sim-1", store, export, export_label="run1")

        assert all(not str(spec.dest).endswith(".gpkg") for spec in store.specs)
