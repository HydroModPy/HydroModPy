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

import hydromodpy.display.runs as display_runs
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
    store: object | None = None,
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
    cfg = SimpleNamespace(display=display)
    setup = SimpleNamespace(workspace=workspace)
    return SimpleNamespace(
        cfg=cfg,
        setup=setup,
        sim_id="deadbeef-dead-beef-dead-beefdeadbeef",
        store=store,
    )


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
    ctx = _make_ctx(enabled=True, figures=[], project_root=tmp_path)
    state = PipelineState(run_id="r", data={"ctx": ctx})

    renderer = MagicMock()
    monkeypatch.setattr(display_runs, "render_figures_for_run", renderer)
    final = DisplayStep().run(state)
    assert final.get("rendered_figures") == []
    renderer.assert_not_called()


def test_display_step_invokes_renderer_when_enabled(monkeypatch, tmp_path):
    # The store is still open at display time: figures read the live run,
    # before the export step drops the intermediates and seals it.
    fake_run = SimpleNamespace(name="baseline")
    fake_store = MagicMock()
    fake_store.__getitem__.return_value = fake_run
    ctx = _make_ctx(
        enabled=True,
        figures=["piezometric_map"],
        project_root=tmp_path,
        store=fake_store,
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


def test_display_step_summary_names_a_figure_the_run_could_not_produce(monkeypatch, tmp_path):
    # A calibration figure on a plain run is skipped for a reason no config
    # option unblocks: the batch summary is where it stays visible.
    fake_store = MagicMock()
    fake_store.__getitem__.return_value = SimpleNamespace(name="baseline")
    ctx = _make_ctx(
        enabled=True,
        figures=["calibration_convergence"],
        project_root=tmp_path,
        store=fake_store,
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
    # Figures are the last reader of the run: they draw from the open store,
    # then export drops the intermediate budget and packs the Zarr.
    from hydromodpy.workflow.orchestrator import standard_steps

    names = [type(s).__name__ for s in standard_steps()]
    assert names[-2:] == ["DisplayStep", "ExportStep"]
