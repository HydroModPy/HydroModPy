"""Unit tests for :class:`DisplayStep` - the 12th pipeline step.

Heavy I/O (catalog open, figure rendering) is kept out of this unit test
via monkey-patching. We verify the *policy* layer:

* honour ``ctx.cfg.display.enabled`` and non-empty ``figures``
* honour ``state.data['skip_display']`` (the ``hmp run --no-display`` hook)
* emit no call when ``sim_id`` or ``ctx`` is missing
* forward the run to the renderer with the right output directory
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import hydromodpy.display.runs as display_runs
from hydromodpy.display.report_profiles import CATCHMENT_GAUGED_DISPLAY_FIGURES
from hydromodpy.workflow.internals.state import PipelineState
from hydromodpy.workflow.steps.display import DisplayStep


def _make_ctx(
    *,
    enabled: bool,
    figures: list[str],
    project_root: Path,
    report: SimpleNamespace | None = None,
) -> SimpleNamespace:
    workspace = SimpleNamespace(
        project_root=project_root,
        root=project_root.parent,
    )
    flow = SimpleNamespace(
        enabled=True,
        streamflow=True,
        piezometry=True,
        budget=False,
        hydrography=True,
        boussinesq_state=True,
    )
    display = SimpleNamespace(
        enabled=enabled,
        figures=figures,
        save=True,
        dpi=150,
        output_dir=Path("figures"),
        flow=flow,
    )
    cfg = SimpleNamespace(display=display, report=report)
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
    ctx = _make_ctx(enabled=True, figures=["piezometric_map"], project_root=tmp_path)
    state = PipelineState(run_id="r", data={"ctx": ctx})

    # Stub the catalog so we don't touch disk.
    fake_run = SimpleNamespace(name="baseline")
    fake_catalog = MagicMock()
    fake_catalog.__enter__.return_value = fake_catalog
    fake_catalog.__exit__.return_value = False
    fake_catalog.__getitem__.return_value = fake_run

    class FakeCatalog:
        @classmethod
        def from_workspace(cls, *args, **kwargs):
            del args, kwargs
            return fake_catalog

    monkeypatch.setattr("hydromodpy.results.catalog.SimulationCatalog", FakeCatalog)
    renderer = MagicMock(return_value=[tmp_path / "figures" / "baseline" / "piezometric_map.png"])
    monkeypatch.setattr(display_runs, "render_figures_for_run", renderer)

    final = DisplayStep().run(state)
    renderer.assert_called_once()
    _, kwargs = renderer.call_args
    assert kwargs["output_dir"] == tmp_path / "figures" / "baseline"
    assert final.get("rendered_figures") == [
        tmp_path / "figures" / "baseline" / "piezometric_map.png"
    ]


def test_display_step_adds_report_profile_figures(monkeypatch, tmp_path):
    report = SimpleNamespace(
        html=SimpleNamespace(
            enabled=True,
            build_at_end=True,
            profile="catchment_gauged",
            strict=False,
        )
    )
    ctx = _make_ctx(enabled=False, figures=["hydrograph"], project_root=tmp_path, report=report)
    state = PipelineState(run_id="r", data={"ctx": ctx})

    fake_run = SimpleNamespace(name="baseline")
    fake_catalog = MagicMock()
    fake_catalog.__enter__.return_value = fake_catalog
    fake_catalog.__exit__.return_value = False
    fake_catalog.__getitem__.return_value = fake_run

    class FakeCatalog:
        @classmethod
        def from_workspace(cls, *args, **kwargs):
            del args, kwargs
            return fake_catalog

    monkeypatch.setattr("hydromodpy.results.catalog.SimulationCatalog", FakeCatalog)
    rendered = [
        tmp_path / "figures" / "baseline" / f"{name}.png"
        for name in CATCHMENT_GAUGED_DISPLAY_FIGURES
    ]
    for path in rendered:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"png")
    renderer = MagicMock(return_value=rendered)
    monkeypatch.setattr(display_runs, "render_figures_for_run", renderer)

    final = DisplayStep().run(state)

    _, kwargs = renderer.call_args
    expected_figures = [
        "hydrograph",
        *[name for name in CATCHMENT_GAUGED_DISPLAY_FIGURES if name != "hydrograph"],
    ]
    assert kwargs["figure_names"] == expected_figures
    effective_cfg = renderer.call_args.args[1]
    assert effective_cfg.enabled is True
    assert effective_cfg.save is True
    assert effective_cfg.flow.budget is True
    assert final.get("report_display_manifest") == (
        tmp_path / "figures" / "baseline" / "report_artifact_manifest.json"
    )
    manifest = json.loads(final.get("report_display_manifest").read_text(encoding="utf-8"))
    assert manifest["profile"] == "catchment_gauged"
    assert manifest["summary"]["artifact_count"] == len(CATCHMENT_GAUGED_DISPLAY_FIGURES)
    assert manifest["summary"]["missing_required_count"] == 0


def test_display_step_standard_pipeline_contains_it():
    from hydromodpy.workflow.orchestrator import standard_steps

    names = [type(s).__name__ for s in standard_steps()]
    assert "DisplayStep" in names
    assert names[-1] == "HtmlReportStep"
