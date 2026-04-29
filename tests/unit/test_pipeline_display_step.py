"""Unit tests for :class:`DisplayStep` - the 12th pipeline step.

Heavy I/O (catalog open, figure rendering) is kept out of this unit test
via monkey-patching. We verify the *policy* layer:

* honour ``ctx.cfg.display.enabled`` and non-empty ``figures``
* honour ``state.data['skip_display']`` (the ``hmp run --no-display`` hook)
* emit no call when ``sim_id`` or ``ctx`` is missing
* forward the run to the renderer with the right output directory
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from hydromodpy.pipeline.steps.step_11_display import DisplayStep
from hydromodpy.workflow.internals.state import PipelineState


def _make_ctx(*, enabled: bool, figures: list[str], project_root: Path) -> SimpleNamespace:
    workspace = SimpleNamespace(
        project_root=project_root,
        root=project_root.parent,
    )
    display = SimpleNamespace(
        enabled=enabled,
        figures=figures,
        save=True,
        dpi=150,
        output_dir=Path("figures"),
    )
    cfg = SimpleNamespace(display=display)
    setup = SimpleNamespace(workspace=workspace)
    return SimpleNamespace(
        cfg=cfg,
        setup=setup,
        sim_id="deadbeef-dead-beef-dead-beefdeadbeef",
    )


def test_display_step_skips_when_flag_set(monkeypatch, tmp_path):
    ctx = _make_ctx(enabled=True, figures=["piezometric_map"], project_root=tmp_path)
    state = PipelineState(run_id="r", data={"ctx": ctx, "skip_display": True})

    renderer = MagicMock()
    monkeypatch.setattr(
        "hydromodpy.pipeline.steps.step_11_display.DisplayStep",
        DisplayStep,
    )
    monkeypatch.setattr(
        "hydromodpy.display.runs.render_figures_for_run",
        renderer,
    )
    final = DisplayStep().run(state)
    assert final.get("rendered_figures") == []
    renderer.assert_not_called()


def test_display_step_skips_when_disabled(monkeypatch, tmp_path):
    ctx = _make_ctx(enabled=False, figures=["piezometric_map"], project_root=tmp_path)
    state = PipelineState(run_id="r", data={"ctx": ctx})

    renderer = MagicMock()
    monkeypatch.setattr(
        "hydromodpy.display.runs.render_figures_for_run",
        renderer,
    )
    final = DisplayStep().run(state)
    assert final.get("rendered_figures") == []
    renderer.assert_not_called()


def test_display_step_skips_when_empty_figure_list(monkeypatch, tmp_path):
    ctx = _make_ctx(enabled=True, figures=[], project_root=tmp_path)
    state = PipelineState(run_id="r", data={"ctx": ctx})

    renderer = MagicMock()
    monkeypatch.setattr(
        "hydromodpy.display.runs.render_figures_for_run",
        renderer,
    )
    final = DisplayStep().run(state)
    assert final.get("rendered_figures") == []
    renderer.assert_not_called()


def test_display_step_invokes_renderer_when_enabled(monkeypatch, tmp_path):
    ctx = _make_ctx(enabled=True, figures=["piezometric_map"], project_root=tmp_path)
    state = PipelineState(run_id="r", data={"ctx": ctx})

    # Stub the catalog so we don't touch disk.
    fake_run = SimpleNamespace(name="baseline")
    fake_catalog = MagicMock()
    fake_catalog.__enter__.return_value = fake_catalog
    fake_catalog.__exit__.return_value = False
    fake_catalog.__getitem__.return_value = fake_run

    monkeypatch.setattr(
        "hydromodpy.results.catalog.SimulationCatalog",
        lambda *args, **kw: fake_catalog,
    )
    renderer = MagicMock(return_value=[tmp_path / "figures" / "baseline" / "piezometric_map.png"])
    monkeypatch.setattr(
        "hydromodpy.display.runs.render_figures_for_run",
        renderer,
    )

    final = DisplayStep().run(state)
    renderer.assert_called_once()
    _, kwargs = renderer.call_args
    assert kwargs["output_dir"] == tmp_path / "figures" / "baseline"
    assert final.get("rendered_figures") == [
        tmp_path / "figures" / "baseline" / "piezometric_map.png"
    ]


def test_display_step_standard_pipeline_contains_it():
    from hydromodpy.pipeline.steps import standard_steps

    names = [type(s).__name__ for s in standard_steps()]
    assert names[-1] == "DisplayStep"
