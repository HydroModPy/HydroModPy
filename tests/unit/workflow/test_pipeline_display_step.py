"""Unit tests for :class:`DisplayStep` - the 12th pipeline step.

Heavy I/O (catalog open, figure rendering) is kept out of this unit test
via monkey-patching. We verify the *policy* layer:

* honour ``ctx.cfg.display.enabled`` and non-empty ``figures``
* honour ``state.data['skip_display']`` (the ``hmp run --no-display`` hook)
* emit no call when ``sim_id`` or ``ctx`` is missing
* forward the run to the renderer with the right output directory
* always summarize the batch, naming every requested figure not produced
"""

from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import hydromodpy.display.runs as display_runs
import hydromodpy.workflow.steps.display as display_step_module
from hydromodpy.core.logging import get_logger
from hydromodpy.core.state.paths import runs_dir_for
from hydromodpy.results.storage.contract import RUN_FIGURES_DIRNAME
from hydromodpy.workflow.internals.state import PipelineState
from hydromodpy.workflow.steps.display import DisplayStep


def _make_ctx(
    *,
    enabled: bool,
    figures: list[str],
    project_root: Path,
    catalogued: bool = False,
) -> SimpleNamespace:
    workspace = SimpleNamespace(
        project_root=project_root,
        root=project_root.parent,
    )
    display = SimpleNamespace(
        enabled=enabled,
        figures=figures,
        save=True,
        dpi=150,
        output_dir=RUN_FIGURES_DIRNAME,
    )
    cfg = SimpleNamespace(
        display=display,
        simulation=SimpleNamespace(
            results=SimpleNamespace(persistence=SimpleNamespace(save_catalog=catalogued))
        ),
    )
    setup = SimpleNamespace(workspace=workspace)
    return SimpleNamespace(
        cfg=cfg,
        setup=setup,
        sim_id="deadbeef-dead-beef-dead-beefdeadbeef",
        effective_results_config=None,
        execution=SimpleNamespace(lightweight=False),
    )


@pytest.fixture
def catalog_handle(monkeypatch):
    """Hand the step a stand-in for the catalog it opens for its own span."""
    from contextlib import contextmanager

    handle = MagicMock()

    @contextmanager
    def _fake_scope(_ctx):
        yield handle

    monkeypatch.setattr(display_step_module, "run_catalog", _fake_scope)
    return handle


def test_display_step_skips_when_flag_set(monkeypatch, tmp_path):
    ctx = _make_ctx(enabled=True, figures=["piezometric_map"], project_root=tmp_path)
    state = PipelineState(run_id="r", data={"ctx": ctx, "skip_display": True})

    renderer = MagicMock()
    monkeypatch.setattr(
        "hydromodpy.workflow.steps.display.DisplayStep",
        DisplayStep,
    )
    monkeypatch.setattr(display_runs, "render_figures_for_run", renderer)
    final = DisplayStep().run(state)
    assert final.get("rendered_figures") == []
    renderer.assert_not_called()


def test_display_step_skips_when_disabled(monkeypatch, tmp_path):
    ctx = _make_ctx(enabled=False, figures=["piezometric_map"], project_root=tmp_path)
    state = PipelineState(run_id="r", data={"ctx": ctx})

    renderer = MagicMock()
    monkeypatch.setattr(display_runs, "render_figures_for_run", renderer)
    final = DisplayStep().run(state)
    assert final.get("rendered_figures") == []
    renderer.assert_not_called()


def test_display_step_skips_when_empty_figure_list(monkeypatch, tmp_path):
    # The run is catalogued on purpose: otherwise the step returns on the
    # "no config, no sim_id or no index" branch and this test would pass
    # without ever reaching the empty-list decision it is named after.
    ctx = _make_ctx(enabled=True, figures=[], project_root=tmp_path, catalogued=True)
    state = PipelineState(run_id="r", data={"ctx": ctx})

    renderer = MagicMock()
    monkeypatch.setattr(display_runs, "render_figures_for_run", renderer)
    final = DisplayStep().run(state)
    assert final.get("rendered_figures") == []
    renderer.assert_not_called()


def test_display_step_says_out_loud_that_it_drew_nothing(monkeypatch, tmp_path, caplog):
    # A run that draws nothing looks exactly like a run whose figure list
    # silently emptied. In TOML a table header swallows every key below it, so
    # a `[display.overrides.<fig>]` written above `figures` takes the list with
    # it, `hmp config check` still passes, and the run renders zero figure. The
    # line has to be readable at the default level or the accident is mute.
    ctx = _make_ctx(enabled=True, figures=[], project_root=tmp_path, catalogued=True)
    state = PipelineState(run_id="r", data={"ctx": ctx})
    monkeypatch.setattr(display_runs, "render_figures_for_run", MagicMock())

    with caplog.at_level("INFO"):
        DisplayStep().run(state)

    message = " ".join(r.getMessage() for r in caplog.records)
    assert "No figure rendered" in message
    assert "[display]" in message


def test_display_step_invokes_renderer_when_enabled(monkeypatch, tmp_path, catalog_handle):
    # The figures open the catalog for their own span and read the live run,
    # before the export step drops the intermediates and seals it.
    catalog_handle.__getitem__.return_value = SimpleNamespace(name="baseline")
    ctx = _make_ctx(
        enabled=True,
        figures=["piezometric_map"],
        project_root=tmp_path,
        catalogued=True,
    )
    state = PipelineState(run_id="r", data={"ctx": ctx})

    expected_dir = runs_dir_for(tmp_path) / "baseline" / RUN_FIGURES_DIRNAME
    written = expected_dir / "piezometric_map.png"
    renderer = MagicMock(
        return_value=display_runs.FigureRenderReport(
            requested=("piezometric_map",),
            rendered=("piezometric_map",),
            written=(written,),
        )
    )
    monkeypatch.setattr(display_runs, "render_figures_for_run", renderer)

    final = DisplayStep().run(state)
    renderer.assert_called_once()
    _, kwargs = renderer.call_args
    assert kwargs["output_dir"] == expected_dir
    assert final.get("rendered_figures") == [written]


def test_display_step_summary_names_a_figure_the_run_could_not_produce(
    monkeypatch, tmp_path, catalog_handle
):
    # A calibration figure on a plain run is skipped for a reason no config
    # option unblocks: the batch summary is where it stays visible.
    catalog_handle.__getitem__.return_value = SimpleNamespace(name="baseline")
    ctx = _make_ctx(
        enabled=True,
        figures=["calibration_convergence"],
        project_root=tmp_path,
        catalogued=True,
    )
    state = PipelineState(run_id="r", data={"ctx": ctx})

    monkeypatch.setattr(
        display_runs,
        "render_figures_for_run",
        MagicMock(
            return_value=display_runs.FigureRenderReport(
                requested=("calibration_convergence",),
                skipped=(
                    display_runs.SkippedFigure(
                        name="calibration_convergence",
                        reason="missing catalog table(s): calibration_trials",
                    ),
                ),
            )
        ),
    )

    records: list[logging.LogRecord] = []
    handler = logging.Handler()
    handler.emit = records.append
    summary_logger = get_logger("hydromodpy.display.runs")
    summary_logger.addHandler(handler)
    try:
        DisplayStep().run(state)
    finally:
        summary_logger.removeHandler(handler)

    messages = [r.getMessage() for r in records if "figure(s)" in r.getMessage()]
    assert messages == [
        "Rendered 0/1 figure(s) -> "
        f"{runs_dir_for(tmp_path) / 'baseline' / RUN_FIGURES_DIRNAME}; 1 skipped: "
        "calibration_convergence (missing catalog table(s): calibration_trials)"
    ]
    assert [r.levelname for r in records if "figure(s)" in r.getMessage()] == ["WARNING"]


def test_display_step_renders_before_the_export_step_seals_the_run():
    # Figures are the last reader of the run: they draw through their own
    # catalog scope, then export drops the intermediate budget and packs the
    # Zarr.
    from hydromodpy.workflow.orchestrator import standard_steps

    names = [type(s).__name__ for s in standard_steps()]
    assert names[-2:] == ["DisplayStep", "ExportStep"]
