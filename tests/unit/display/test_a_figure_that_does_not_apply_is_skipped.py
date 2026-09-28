"""A figure that finds it does not apply is skipped, even under on_error = "raise".

The composite calibration of example 04 samples K and Sy together. Its promoted
run lists the figures of a one-parameter search, and the downslope crossing
raised "this figure reads one calibrated parameter" mid-render, so
``on_error = "raise"`` failed the promotion of a search that had converged.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from hydromodpy.display.config import DisplayConfig
from hydromodpy.display.figure import FigureNotApplicable, FigureSpec
from hydromodpy.display.figures._trial_diagnostics import TrialTable
from hydromodpy.results.storage.contract import RUN_FIGURES_DIRNAME

pytestmark = pytest.mark.unit


class _Run:
    sim_id = "11111111-2222-3333-4444-555555555555"
    name = "composite"

    def has_field(self, variable: str, *, subgroup: str | None = None) -> bool:
        del variable, subgroup
        return False


class _OneParameterFigure:
    def __init__(self, name: str) -> None:
        self.spec = FigureSpec(name=name, title=name)

    def unavailable_reason(self, sim) -> str | None:
        del sim
        return None

    def plot(self, sim, *, dpi: int = 150, save_path: Path | None = None, **kw) -> None:
        raise FigureNotApplicable("this figure reads one calibrated parameter")


class _Figure(_OneParameterFigure):
    def plot(self, sim, *, dpi: int = 150, save_path: Path | None = None, **kw) -> None:
        if save_path is not None:
            Path(save_path).write_bytes(b"png")


def _config(*figures: str) -> DisplayConfig:
    return DisplayConfig.model_construct(
        enabled=True,
        save=True,
        dpi=150,
        preset="default",
        backend="auto",
        show=False,
        on_error="raise",
        cmap="viridis",
        overrides={},
        output_dir=RUN_FIGURES_DIRNAME,
        figures=list(figures),
    )


def test_the_batch_skips_it_and_draws_the_rest(tmp_path: Path, monkeypatch) -> None:
    import hydromodpy.display.runs as runs

    figures = {"crossing": _OneParameterFigure("crossing"), "hydrograph": _Figure("hydrograph")}
    monkeypatch.setattr(runs, "_get_figure", figures.__getitem__)

    report = runs.render_figures_for_run(
        _Run(), _config("crossing", "hydrograph"), output_dir=tmp_path
    )

    assert report.rendered == ("hydrograph",)
    assert [s.name for s in report.skipped] == ["crossing"]
    assert "one calibrated parameter" in report.skipped[0].reason


def test_two_sampled_parameters_without_a_name_do_not_apply() -> None:
    table = TrialTable(
        frame=pd.DataFrame({"K": [1e-5, 2e-5], "Sy": [0.05, 0.06]}), parameters=("K", "Sy")
    )

    with pytest.raises(FigureNotApplicable, match="K, Sy"):
        table.parameter_values()
    name, values = table.parameter_values("K")
    assert name == "K"
    assert list(values) == [1e-5, 2e-5]
