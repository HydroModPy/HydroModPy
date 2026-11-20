"""The display step draws the figures of a sealed run and never undoes the seal.

The step runs after the seal. It honours the display switch and the figure list and
forwards the run to the renderer. Each figure carries the
identity block of the run labelled the day it is drawn (label, rules, date), in the
PNG chunk and in the visible footer. A figure that fails under ``on_error = "raise"``
raises a ``DisplayError`` that names ``hmp show --figure``.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import hydromodpy.display.runs as display_runs
import hydromodpy.workflow.steps.display as display_steps
import hydromodpy.workflow.steps.export as export_step_module
from hydromodpy.core.exceptions import DisplayError
from hydromodpy.core.state.layout import runs_dir_for
from hydromodpy.display.config import DisplayConfig
from hydromodpy.display.runs import figures_dir_of
from hydromodpy.results.identity import read_identity_from
from hydromodpy.results.ledger import Ledger
from hydromodpy.results.record.manifest import is_sealed
from hydromodpy.workflow.state import PipelineState
from hydromodpy.workflow.steps.display import DisplayStep, draw_after
from tests._helpers.run_stores import RUN_NAME, seal_demo_run


def fake_ctx(
    *, enabled: bool, figures: list[dict], project_root: Path, catalogued: bool = False
) -> SimpleNamespace:
    display = SimpleNamespace(enabled=enabled, figure=figures, presets={}, dpi=300)
    cfg = SimpleNamespace(
        display=display,
        simulation=SimpleNamespace(
            results=SimpleNamespace(persistence=SimpleNamespace(save_catalog=catalogued))
        ),
    )
    workspace = SimpleNamespace(project_root=project_root, root=project_root.parent)
    return SimpleNamespace(
        cfg=cfg,
        setup=SimpleNamespace(workspace=workspace),
        run_dir=runs_dir_for(project_root) / "baseline",
        sim_id="deadbeef-dead-beef-dead-beefdeadbeef",
        execution=SimpleNamespace(lightweight=False),
        attempt=1,
    )


@pytest.fixture
def catalog_handle(monkeypatch):
    """Stand in for the sealed run store the step opens for its own span."""
    handle = MagicMock()

    @contextmanager
    def fake_scope(_ctx):
        yield handle

    monkeypatch.setattr(export_step_module, "sealed_run_store", fake_scope)
    return handle


# The run is catalogued on the empty list on purpose. Otherwise the step returns on
# the "no config, no sim_id or no index" branch and never reaches the list decision.
SKIPS = [
    pytest.param(True, [{"variable": "head"}], False, {"skip_display": True}, id="skip flag set"),
    pytest.param(False, [{"variable": "head"}], False, {}, id="display disabled"),
    pytest.param(True, [], True, {}, id="empty figure list"),
]


@pytest.mark.parametrize(("enabled", "figures", "catalogued", "extra"), SKIPS)
def test_step_skips_the_renderer(
    monkeypatch, tmp_path, enabled, figures, catalogued, extra
) -> None:
    ctx = fake_ctx(enabled=enabled, figures=figures, project_root=tmp_path, catalogued=catalogued)
    renderer = MagicMock()
    monkeypatch.setattr(display_runs, "draw_requests", renderer)

    final = DisplayStep().run(PipelineState(run_id="r", data={"ctx": ctx} | extra))

    assert final.get("rendered_figures") == []
    renderer.assert_not_called()


def test_step_says_it_drew_nothing(monkeypatch, tmp_path, caplog) -> None:
    # A run that draws nothing looks like a run whose figure list emptied by accident,
    # so the line must be readable at the default level.
    ctx = fake_ctx(enabled=True, figures=[], project_root=tmp_path, catalogued=True)
    monkeypatch.setattr(display_runs, "draw_requests", MagicMock())

    with caplog.at_level("INFO"):
        DisplayStep().run(PipelineState(run_id="r", data={"ctx": ctx}))

    message = " ".join(r.getMessage() for r in caplog.records)
    assert "No figure rendered" in message
    assert "[display]" in message


@pytest.fixture
def sealed(tmp_path: Path) -> tuple[Path, Path, str]:
    project = tmp_path / "project"
    run_dir, sim_id = seal_demo_run(project)
    return project, run_dir, sim_id


def sealed_ctx(
    project: Path, run_dir: Path, sim_id: str, display: DisplayConfig
) -> SimpleNamespace:
    return SimpleNamespace(
        cfg=SimpleNamespace(
            display=display,
            simulation=SimpleNamespace(
                results=SimpleNamespace(persistence=SimpleNamespace(save_catalog=True))
            ),
        ),
        setup=SimpleNamespace(workspace=SimpleNamespace(project_root=project)),
        run_dir=run_dir,
        sim_id=sim_id,
        execution=SimpleNamespace(lightweight=False),
        attempt=1,
        level="result",
    )


def run_display(ctx: SimpleNamespace) -> PipelineState:
    return DisplayStep().run(PipelineState(run_id="r", data={"ctx": ctx}))


def test_figure_carries_label_rule_and_date(sealed) -> None:
    project, run_dir, sim_id = sealed
    assert is_sealed(run_dir)

    final = run_display(
        sealed_ctx(
            project,
            run_dir,
            sim_id,
            DisplayConfig(figure=[{"variable": "head", "name": "water_budget"}]),
        )
    )

    (figure,) = final.get("rendered_figures")
    assert figure == figures_dir_of(run_dir) / "water_budget.png"
    identity = read_identity_from(figure)
    assert identity is not None and identity.sim_id == sim_id
    assert identity.label is not None
    assert identity.rule_version
    assert identity.label_date == datetime.now(UTC).date()
    footer = identity.footer_text()
    assert footer.endswith(f"{identity.label}, rule {identity.rule_version}, {identity.label_date}")
    assert "unlabelled" not in footer
    assert Ledger.read(figures_dir_of(run_dir)).entry_for("water_budget.png") is not None


def breaks(*_args, **_keywords):
    raise RuntimeError("the axes broke")


def test_failing_figure_under_raise_names_hmp_show(monkeypatch, sealed) -> None:
    project, run_dir, sim_id = sealed
    monkeypatch.setattr(display_runs, "render", breaks)
    display = DisplayConfig(figure=[{"variable": "head", "name": "water_budget"}], on_error="raise")

    with pytest.raises(DisplayError) as raised:
        run_display(sealed_ctx(project, run_dir, sim_id, display))

    assert str(raised.value).startswith(
        f"run {RUN_NAME} is sealed; draw the figure again with hmp show {RUN_NAME} "
        "--figure water_budget: "
    )
    assert "the axes broke" in str(raised.value)
    assert isinstance(raised.value.__cause__, RuntimeError)
    assert is_sealed(run_dir)


def test_failing_figure_under_warn_is_skipped(monkeypatch, sealed) -> None:
    project, run_dir, sim_id = sealed
    monkeypatch.setattr(display_runs, "render", breaks)
    display = DisplayConfig(figure=[{"variable": "head", "name": "water_budget"}], on_error="warn")

    final = run_display(sealed_ctx(project, run_dir, sim_id, display))

    assert final.get("rendered_figures") == []
    assert is_sealed(run_dir)


def after_ctx(tmp_path: Path) -> SimpleNamespace:
    figures = [
        {"variable": "head", "name": "early", "when": "after:extract"},
        {"variable": "head", "name": "mid", "when": "after:derive"},
        {"variable": "head", "name": "late"},
    ]
    ctx = fake_ctx(enabled=True, figures=figures, project_root=tmp_path, catalogued=True)
    ctx.cfg.display = DisplayConfig(figure=figures, on_error="raise")
    return ctx


def test_draw_after_draws_only_its_step(monkeypatch, tmp_path) -> None:
    ctx = after_ctx(tmp_path)
    handle = MagicMock()

    @contextmanager
    def fake_store(_ctx):
        yield handle

    monkeypatch.setattr(display_steps, "run_store", fake_store)
    renderer = MagicMock(return_value=SimpleNamespace(written=[Path("mid.png")]))
    monkeypatch.setattr(display_runs, "draw_requests", renderer)
    state = PipelineState(run_id="r", data={"ctx": ctx})

    assert draw_after(state, "derive") == [Path("mid.png")]
    assert renderer.call_args.kwargs["when"] == "after:derive"
    assert renderer.call_args.kwargs["on_error"] == "warn"
    renderer.reset_mock()
    assert draw_after(state, "build_mesh") == []
    assert draw_after(state, "export") == []
    assert (
        draw_after(PipelineState(run_id="r", data={"ctx": ctx, "skip_display": True}), "derive")
        == []
    )
    renderer.assert_not_called()
