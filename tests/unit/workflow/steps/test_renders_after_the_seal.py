"""Figures render the sealed run, carry its label, and never undo the seal.

The display step runs after the seal. It opens the store of the sealed run on
its directory, so each figure carries the identity block of the run labelled
the day it is drawn: the label, the rules it follows and the date, in the PNG
chunk and in the visible footer. A figure that fails under
``on_error = "raise"`` leaves the run sealed and raises a ``DisplayError``
that names ``hmp viz show``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import hydromodpy.display.runs as display_runs
from hydromodpy.core.exceptions import DisplayError
from hydromodpy.display.config import DisplayConfig
from hydromodpy.display.figure import BaseFigure, FigureSpec
from hydromodpy.display.runs import figures_dir_of
from hydromodpy.results.identity import read_identity_from
from hydromodpy.results.ledger import Ledger
from hydromodpy.results.record.manifest import is_sealed
from hydromodpy.workflow.state import PipelineState
from hydromodpy.workflow.steps.display import DisplayStep
from tests._helpers.run_stores import RUN_NAME, seal_demo_run


@pytest.fixture
def sealed(tmp_path: Path) -> tuple[Path, Path, str]:
    project = tmp_path / "project"
    run_dir, sim_id = seal_demo_run(project)
    return project, run_dir, sim_id


def _ctx(project: Path, run_dir: Path, sim_id: str, display: DisplayConfig) -> SimpleNamespace:
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


def _run_display(ctx: SimpleNamespace) -> PipelineState:
    return DisplayStep().run(PipelineState(run_id="r", data={"ctx": ctx}))


def test_a_figure_of_a_sealed_run_carries_its_label_rule_and_date(sealed) -> None:
    project, run_dir, sim_id = sealed
    assert is_sealed(run_dir)

    final = _run_display(_ctx(project, run_dir, sim_id, DisplayConfig(figures=["water_budget"])))

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


class _Breaks(BaseFigure):
    spec = FigureSpec(name="water_budget", title="Breaks")

    def render(self, subject: Any, ax: Any, **_: Any) -> Any:
        raise RuntimeError("the axes broke")


def test_a_figure_that_fails_after_the_seal_names_hmp_viz_show(monkeypatch, sealed) -> None:
    project, run_dir, sim_id = sealed
    monkeypatch.setattr(display_runs, "_get_figure", lambda _name: _Breaks())
    display = DisplayConfig(figures=["water_budget"], on_error="raise")

    with pytest.raises(DisplayError) as raised:
        _run_display(_ctx(project, run_dir, sim_id, display))

    assert str(raised.value).startswith(
        f"run {RUN_NAME} is sealed; draw the figure again with hmp viz show "
        f"{RUN_NAME} water_budget: "
    )
    assert "the axes broke" in str(raised.value)
    assert isinstance(raised.value.__cause__, RuntimeError)
    assert is_sealed(run_dir)


def test_a_figure_that_fails_under_warn_is_skipped_and_the_step_ends(monkeypatch, sealed) -> None:
    project, run_dir, sim_id = sealed
    monkeypatch.setattr(display_runs, "_get_figure", lambda _name: _Breaks())
    display = DisplayConfig(figures=["water_budget"], on_error="warn")

    final = _run_display(_ctx(project, run_dir, sim_id, display))

    assert final.get("rendered_figures") == []
    assert is_sealed(run_dir)


def test_the_display_step_waits_for_the_seal() -> None:
    assert DisplayStep().depends_on() == ("seal",)
