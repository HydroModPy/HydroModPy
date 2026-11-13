"""The display step draws the figures of a sealed run and never undoes the seal.

The step runs after the seal. It honours the display switches and the figure list,
forwards the run to the renderer, and sums up the batch. Each figure carries the
identity block of the run labelled the day it is drawn (label, rules, date), in the
PNG chunk and in the visible footer. A figure that fails under ``on_error = "raise"``
raises a ``DisplayError`` that names ``hmp show --figure``.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

import hydromodpy.display.runs as display_runs
import hydromodpy.workflow.steps.export as export_step_module
from hydromodpy.core.exceptions import DisplayError
from hydromodpy.core.logging import get_logger
from hydromodpy.core.state.layout import runs_dir_for
from hydromodpy.display.config import DisplayConfig
from hydromodpy.display.figure import BaseFigure, FigureSpec
from hydromodpy.display.runs import figures_dir_of
from hydromodpy.results.identity import read_identity_from
from hydromodpy.results.ledger import Ledger
from hydromodpy.results.record.manifest import is_sealed
from hydromodpy.results.storage.contract import RUN_FIGURES_DIRNAME
from hydromodpy.workflow.state import PipelineState
from hydromodpy.workflow.steps.display import DisplayStep
from tests._helpers.run_stores import RUN_NAME, seal_demo_run


def fake_ctx(
    *, enabled: bool, figures: list[str], project_root: Path, catalogued: bool = False
) -> SimpleNamespace:
    display = SimpleNamespace(
        enabled=enabled, figures=figures, figure=[], presets={}, save=True, dpi=150
    )
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
    pytest.param(True, ["piezometric_map"], False, {"skip_display": True}, id="skip flag set"),
    pytest.param(False, ["piezometric_map"], False, {}, id="display disabled"),
    pytest.param(True, [], True, {}, id="empty figure list"),
]


@pytest.mark.parametrize(("enabled", "figures", "catalogued", "extra"), SKIPS)
def test_step_skips_the_renderer(
    monkeypatch, tmp_path, enabled, figures, catalogued, extra
) -> None:
    ctx = fake_ctx(enabled=enabled, figures=figures, project_root=tmp_path, catalogued=catalogued)
    renderer = MagicMock()
    monkeypatch.setattr(display_runs, "render_figures_for_run", renderer)

    final = DisplayStep().run(PipelineState(run_id="r", data={"ctx": ctx} | extra))

    assert final.get("rendered_figures") == []
    renderer.assert_not_called()


def test_step_says_it_drew_nothing(monkeypatch, tmp_path, caplog) -> None:
    # In TOML a table header swallows every key below it, so a
    # `[display.overrides.<fig>]` written above `figures` takes the list with it,
    # `hmp check` still passes and the run renders zero figure. The line must be
    # readable at the default level or the accident is mute.
    ctx = fake_ctx(enabled=True, figures=[], project_root=tmp_path, catalogued=True)
    monkeypatch.setattr(display_runs, "render_figures_for_run", MagicMock())

    with caplog.at_level("INFO"):
        DisplayStep().run(PipelineState(run_id="r", data={"ctx": ctx}))

    message = " ".join(r.getMessage() for r in caplog.records)
    assert "No figure rendered" in message
    assert "[display]" in message


def test_summary_names_a_figure_the_run_could_not_produce(
    monkeypatch, tmp_path, catalog_handle
) -> None:
    # A calibration figure on a plain run is skipped for a reason no config option
    # unblocks. It is no warning: a milestone line counts it and an INFO line
    # (--verbose) names it with its reason.
    catalog_handle.__getitem__.return_value = SimpleNamespace(name="baseline")
    ctx = fake_ctx(
        enabled=True,
        figures=["calibration_convergence"],
        project_root=tmp_path,
        catalogued=True,
    )
    report = display_runs.FigureRenderReport(
        requested=("calibration_convergence",),
        skipped=(
            display_runs.SkippedFigure(
                name="calibration_convergence",
                reason="missing catalog table(s): calibration_trials",
            ),
        ),
    )
    monkeypatch.setattr(display_runs, "render_figures_for_run", MagicMock(return_value=report))

    records: list[logging.LogRecord] = []
    handler = logging.Handler()
    handler.emit = records.append
    summary_logger = get_logger("hydromodpy.display.runs")
    previous_level = summary_logger.level
    summary_logger.setLevel(logging.INFO)
    summary_logger.addHandler(handler)
    try:
        DisplayStep().run(PipelineState(run_id="r", data={"ctx": ctx}))
    finally:
        summary_logger.removeHandler(handler)
        summary_logger.setLevel(previous_level)

    figures_dir = runs_dir_for(tmp_path) / "baseline" / RUN_FIGURES_DIRNAME
    assert [(r.levelname, r.getMessage()) for r in records] == [
        ("INFO", f"Rendered 0/1 figure(s) -> {figures_dir}; 1 not applicable to this run"),
        (
            "INFO",
            "Not applicable to this run: "
            "calibration_convergence (missing catalog table(s): calibration_trials)",
        ),
    ]


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
        sealed_ctx(project, run_dir, sim_id, DisplayConfig(figures=["water_budget"]))
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


class BreaksFigure(BaseFigure):
    spec = FigureSpec(name="water_budget", title="Breaks")

    def render(self, subject: Any, ax: Any, **_: Any) -> Any:
        raise RuntimeError("the axes broke")


def test_failing_figure_under_raise_names_hmp_show(monkeypatch, sealed) -> None:
    project, run_dir, sim_id = sealed
    monkeypatch.setattr(display_runs, "_get_figure", lambda _name: BreaksFigure())
    display = DisplayConfig(figures=["water_budget"], on_error="raise")

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
    monkeypatch.setattr(display_runs, "_get_figure", lambda _name: BreaksFigure())
    display = DisplayConfig(figures=["water_budget"], on_error="warn")

    final = run_display(sealed_ctx(project, run_dir, sim_id, display))

    assert final.get("rendered_figures") == []
    assert is_sealed(run_dir)
