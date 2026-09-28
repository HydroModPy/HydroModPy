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
    """Fake store that records the requests ``_auto_export`` hands it, writing empty files."""

    def __init__(self, project_path: Path, *, failing: tuple[str, ...] = ()):
        self.project_path = project_path
        self.requests: list = []
        self.failing = failing

    def export(self, sim_id, request, *, default_folder):
        self.requests.append(request)
        if request.variables in self.failing:
            raise ValueError(f"cannot write {request.variables}")
        default_folder.mkdir(parents=True, exist_ok=True)
        path = default_folder / f"{request.variables}.out"
        path.write_text("")
        return [path]


def _requests(*blocks: dict) -> list:
    from hydromodpy.core.config_kit.export_spec import load_export_requests

    return load_export_requests(list(blocks))


class TestAutoExportRequests:
    """``[[export]]`` blocks run in the order of the file; the run formats wait for the seal."""

    def test_the_data_requests_run_in_file_order_and_the_run_formats_wait(self, tmp_path):
        store = _RecordingStore(tmp_path)
        requests = _requests(
            {"variables": "head", "time": "last"},
            {"variables": "all", "format": "package"},
            {"variables": "discharge"},
        )

        written = post_run_module.auto_export_results(
            sim_id="sim-1", store=store, export_requests=requests, save_catalog=True, run_id="run1"
        )
        assert [request.variables for request in store.requests] == ["head", "discharge"]
        assert [path.name for path in written] == ["head.out", "discharge.out"]
        assert (tmp_path / "share" / "run1" / "RUN.txt").is_file()

        store.requests.clear()
        packaged = post_run_module.auto_export_package(
            sim_id="sim-1", store=store, export_requests=requests, save_catalog=True, run_id="run1"
        )
        assert [request.output_format.value for request in store.requests] == ["package"]
        assert [path.name for path in packaged] == ["all.out"]

    def test_a_failed_request_does_not_stop_the_next_one(self, tmp_path):
        store = _RecordingStore(tmp_path, failing=("head",))
        requests = _requests({"variables": "head"}, {"variables": "discharge"})

        with pytest.raises(RuntimeError, match=r"export request 1 \(variables = head\)"):
            post_run_module.auto_export_results(
                sim_id="sim-1",
                store=store,
                export_requests=requests,
                save_catalog=True,
                run_id="run1",
            )
        assert [request.variables for request in store.requests] == ["head", "discharge"]

    def test_no_catalog_writes_nothing(self, tmp_path):
        store = _RecordingStore(tmp_path)
        written = post_run_module.auto_export_results(
            sim_id="sim-1",
            store=store,
            export_requests=_requests({"variables": "head"}),
            save_catalog=False,
        )
        assert written == []
        assert store.requests == []

    def test_the_console_says_once_how_many_files_and_where(self, tmp_path, caplog):
        import logging

        caplog.set_level(logging.INFO, logger=post_run_module.logger.name)
        post_run_module.announce_exports(
            [tmp_path / "a.tif", tmp_path / "b.csv"], tmp_path / "share" / "run1"
        )
        post_run_module.announce_exports([], tmp_path / "share" / "run1")
        lines = [record.getMessage() for record in caplog.records]
        assert len(lines) == 1
        assert lines[0].startswith("Exported 2 file(s) -> ")
        assert lines[0].endswith("run1")
