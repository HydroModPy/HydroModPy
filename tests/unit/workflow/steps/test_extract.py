"""The extract step."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from hydromodpy.core.budget_terms import BudgetKeep
from hydromodpy.core.state.execution import ExecutionRegistry
from hydromodpy.simulation.planning.plan import ProcessRun, SimulationPlan
from hydromodpy.simulation.planning.results_config import ResultsConfig
from hydromodpy.workflow.state import PipelineState
from hydromodpy.workflow.steps import extract
from hydromodpy.workflow.steps.extract import ExtractStep
from tests._helpers.run_stores import open_run_store


def test_extract_step_extracts_solver_outputs(monkeypatch, tmp_path: Path) -> None:
    run = ProcessRun(
        id="flow_main::fake",
        process_id="flow_main",
        process_type="flow",
        solver="fake",
    )
    plan = SimulationPlan(name="run", description="run", runs=(run,))
    results = ResultsConfig()
    output_dir = tmp_path / "solver"
    output_dir.mkdir()
    calls: list[tuple[str, str, Path]] = []

    planned = BudgetKeep.of_terms(("drain",))

    def _extract_run_outputs(*, ctx, sim_id, results_config, store, budget_terms) -> None:
        calls.append((ctx.run.id, sim_id, ctx.output_dir))
        assert results_config is results
        assert store == "store"
        assert budget_terms is planned

    monkeypatch.setattr(
        "hydromodpy.simulation.extraction.post_run.extract_run_outputs",
        _extract_run_outputs,
    )

    ingested: list[tuple[object, str]] = []
    monkeypatch.setattr(
        "hydromodpy.workflow.steps.extract.step_ingest_observations",
        lambda ctx, sim_id, *, store: ingested.append((ctx, sim_id)),
    )

    @contextmanager
    def _fake_scope(_ctx):
        yield "store"

    monkeypatch.setattr("hydromodpy.workflow.steps.extract.run_store", _fake_scope)

    ctx = SimpleNamespace(
        # A real registry, not a namespace: the step builds its run contexts
        # through ``RunContext.of``, so a double has to carry every scope that
        # path reads rather than the ones this test happens to assert on.
        execution=ExecutionRegistry(
            lightweight=False,
            simulation_plan=plan,
            output_dirs_by_run_id={run.id: output_dir},
        ),
        setup=SimpleNamespace(workspace=object()),
        sim_id="sim-1",
        loaded_data=None,
        cfg=SimpleNamespace(simulation=SimpleNamespace(results=results)),
        budget_terms=planned,
    )
    state = PipelineState(run_id="rid", data={"ctx": ctx})

    out = ExtractStep().run(state)

    assert calls == [(run.id, "sim-1", output_dir)]
    # Observations are ingested in the same step, after solver extraction.
    assert ingested == [(ctx, "sim-1")]
    assert out.data["extraction_summary"] == {"runs": 1}


def _uncomputed_context(tmp_path: Path, results: ResultsConfig, display) -> SimpleNamespace:
    run = ProcessRun(
        id="flow_main::modflow6",
        process_id="flow_main",
        process_type="flow",
        solver="modflow6",
    )
    plan = SimulationPlan(name="run", description="run", runs=(run,))
    output_dir = tmp_path / "solver"
    output_dir.mkdir()
    ctx = SimpleNamespace(
        execution=ExecutionRegistry(
            lightweight=False,
            simulation_plan=plan,
            output_dirs_by_run_id={run.id: output_dir},
        ),
        setup=SimpleNamespace(workspace=object()),
        sim_id="sim-1",
        loaded_data=None,
        cfg=SimpleNamespace(
            simulation=SimpleNamespace(results=results),
            display=display,
            export=[],
            calibration=None,
            observation=None,
        ),
        budget_terms=None,
    )
    return ctx


def _stub_extraction(monkeypatch) -> list[BudgetKeep]:
    seen: list[BudgetKeep] = []
    monkeypatch.setattr(
        "hydromodpy.simulation.extraction.post_run.extract_run_outputs",
        lambda *, budget_terms, **_kwargs: seen.append(budget_terms),
    )
    monkeypatch.setattr(
        "hydromodpy.workflow.steps.extract.step_ingest_observations",
        lambda ctx, sim_id, *, store: None,
    )

    @contextmanager
    def _fake_scope(_ctx):
        yield "store"

    monkeypatch.setattr("hydromodpy.workflow.steps.extract.run_store", _fake_scope)
    return seen


def test_extract_step_decides_the_budget_when_planning_did_not(monkeypatch, tmp_path) -> None:
    """A pipeline entered at extraction still extracts under the run's policy."""
    from hydromodpy.display.config import DisplayConfig

    seen = _stub_extraction(monkeypatch)
    ctx = _uncomputed_context(
        tmp_path,
        ResultsConfig(keep_per_cell_budget=False),
        DisplayConfig(figures=["recharge_map"]),
    )

    ExtractStep().run(PipelineState(run_id="rid", data={"ctx": ctx}))

    assert seen == [BudgetKeep.of_terms(("recharge",))]
    assert ctx.budget_terms == BudgetKeep.of_terms(("recharge",))


def test_no_display_keeps_what_the_figures_read(monkeypatch, tmp_path) -> None:
    """A display choice of the launch changes no data."""
    from hydromodpy.core.budget_terms import budget_terms_for_fields
    from hydromodpy.display import figure_registry
    from hydromodpy.display.config import DisplayConfig

    seen = _stub_extraction(monkeypatch)
    results = ResultsConfig(keep_per_cell_budget=False)
    ctx = _uncomputed_context(tmp_path, results, DisplayConfig(figures=["recharge_map"]))
    ExtractStep().run(PipelineState(run_id="rid", data={"ctx": ctx, "skip_display": True}))
    spec = figure_registry.get("recharge_map").spec
    assert seen[-1] == BudgetKeep.of_terms(
        budget_terms_for_fields((*spec.required_fields, *spec.optional_fields))
    )


# --- test_modpath_ingestion ---
# Unit tests for ``workflow.steps.extract``: the seepage raster rebuilt from a run store.


class _FakeRasterSrc:
    height = 2
    width = 2

    def __enter__(self) -> _FakeRasterSrc:
        return self

    def __exit__(self, *exc: object) -> None:
        pass


def test_restore_seepage_raster_writes_tif(tmp_path: Path, monkeypatch) -> None:
    base_raster = tmp_path / "base.tif"
    base_raster.write_text("dummy")
    seepage_tif = tmp_path / "_postprocess" / "_rasters" / "seepage_areas_t(0).tif"
    array = np.array([[1.0, 0.0], [0.0, -9999.0]], dtype=float)

    with open_run_store(tmp_path / "project", n_cells=4) as store:
        store.write_field(store.sim_id, "seepage_mask", 0, array.ravel(), n_timesteps=1)
        run_dir = store.run_dir
    monkeypatch.setattr(extract.rasterio, "open", lambda *_a, **_kw: _FakeRasterSrc())

    captured: dict[str, object] = {}

    def _fake_export_tif(base_dem_path, data, dst_path, nodata):
        captured["base"] = base_dem_path
        captured["data"] = np.asarray(data, dtype=float)
        captured["dst"] = dst_path
        captured["nodata"] = nodata
        Path(dst_path).write_text("dummy")

    monkeypatch.setattr(extract, "export_tif", _fake_export_tif)

    ok = extract.restore_seepage_raster_from_store(run_dir, base_raster, seepage_tif)

    assert ok is True
    assert seepage_tif.is_file()
    assert captured["base"] == str(base_raster)
    np.testing.assert_array_equal(captured["data"], array)
    assert captured["dst"] == str(seepage_tif)
    assert captured["nodata"] == -9999.0


def test_restore_seepage_raster_returns_false_when_base_missing(tmp_path: Path) -> None:
    base_raster = tmp_path / "missing.tif"
    seepage_tif = tmp_path / "out.tif"
    assert extract.restore_seepage_raster_from_store(tmp_path, base_raster, seepage_tif) is False


def test_restore_seepage_raster_returns_false_when_the_run_has_no_field(tmp_path: Path) -> None:
    base_raster = tmp_path / "base.tif"
    base_raster.write_text("dummy")
    seepage_tif = tmp_path / "out.tif"
    with open_run_store(tmp_path / "project", n_cells=4) as store:
        run_dir = store.run_dir

    assert extract.restore_seepage_raster_from_store(run_dir, base_raster, seepage_tif) is False
