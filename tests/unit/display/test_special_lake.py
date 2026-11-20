"""The lake abacus figure on a small run with one lake and on a run without."""

import numpy as np
import pytest

import hydromodpy as hmp
from hydromodpy.display import static
from hydromodpy.display.special import lake_abacus_comparison
from hydromodpy.display.subject import FigureNotApplicable
from hydromodpy.display.theme import THEMES
from hydromodpy.results.catalog.indexer import rebuild_index
from hydromodpy.results.storage.attempt import close_sealed_attempt
from hydromodpy.results.storage.sealing import seal_completed
from tests._helpers.run_stores import open_run_store

THEME = THEMES["default"]
STAGE = np.array([20.0, 25.0, 30.0])
REAL = np.array([0.0, 2.0e6, 8.0e6])


def lake_run(project, real=REAL, sim=None, lakes=("pond",)):
    store = open_run_store(project, "lake", n_cells=1, n_timesteps=1)
    for lake in lakes:
        store.write_lake_abacus(
            store.sim_id, lake, stage=STAGE, real_volume=real,
            sim_volume=REAL * 1.1 if sim is None else sim,
            real_sarea=STAGE * 1e4, sim_sarea=STAGE * 9e3,
        )  # fmt: skip
    seal_completed(store)
    close_sealed_attempt(store.run_dir)
    rebuild_index(project)
    return hmp.open(project).store["lake"]


def test_the_figure_draws_both_curves_of_volume_and_area_and_the_full_pool_gap(tmp_path):
    ax = static.new_figure(THEME).axes[0]
    lake_abacus_comparison.draw(lake_run(tmp_path / "p"), ax, THEME)
    assert [line.get_label() for line in ax.get_lines()] == ["reference, volume", "carved mesh, volume", "reference, area", "carved mesh, area"]  # fmt: skip
    assert ax.get_lines()[0].get_xdata()[2] == pytest.approx(8.0)
    assert "+10.0 % volume" in " ".join(t.get_text() for t in ax.texts)


def test_a_run_without_a_lake_is_not_applicable(stored_run):
    ax = static.new_figure(THEME).axes[0]
    with pytest.raises(FigureNotApplicable, match="no lake abacus"):
        lake_abacus_comparison.draw(stored_run, ax, THEME)


class Held:
    """A run whose config snapshot is replaced, every other read going to the run."""

    def __init__(self, run, snapshot):
        self._run, self.config_snapshot = run, snapshot

    def __getattr__(self, name):
        return getattr(self._run, name)


def outlets(**lakes):
    return {"flow": {"sinks_sources": {"lakes": {k: {"outlets": [{"invert": v}]} for k, v in lakes.items()}}}}  # fmt: skip


@pytest.mark.parametrize(
    ("snapshot", "level"),
    [
        (outlets(pond="27.5 m"), 27.5),
        (outlets(other=26), 26.0),  # the lake is not named, so the first outlet of the config holds
        (None, None),
        ({"flow": {}}, None),
        (outlets(pond="high"), None),
    ],
)
def test_the_weir_level_is_the_first_invert_of_the_lake_in_the_config(snapshot, level):
    assert lake_abacus_comparison._weir_level(Held(None, snapshot), "pond") == level


def test_the_figure_draws_the_weir_line_when_the_config_holds_the_invert(tmp_path):
    run = Held(lake_run(tmp_path / "p"), outlets(pond="27.5 m"))
    ax = static.new_figure(THEME).axes[0]
    lake_abacus_comparison.draw(run, ax, THEME)
    weir = next(line for line in ax.get_lines() if line.get_label() == "weir level")
    assert list(weir.get_ydata()) == [27.5, 27.5]
    assert "Weir level not stored in the run" not in " ".join(t.get_text() for t in ax.texts)


def test_a_curve_without_a_finite_pair_has_no_fit_and_an_empty_pool_has_no_gap(tmp_path):
    empty = np.zeros(3)
    run = lake_run(tmp_path / "p", real=empty, sim=np.full(3, np.nan))
    ax = static.new_figure(THEME).axes[0]
    lake_abacus_comparison.draw(run, ax, THEME)
    note = " ".join(t.get_text() for t in ax.texts)
    assert "Carved volume" not in note and "Full pool" not in note
    assert "Carved area: NSE" in note and "Weir level not stored in the run" in note


def test_the_figure_names_the_largest_of_several_lakes_unless_one_is_asked(tmp_path):
    run = lake_run(tmp_path / "p", lakes=("pond", "tarn"))
    ax = static.new_figure(THEME).axes[0]
    lake_abacus_comparison.draw(run, ax, THEME)
    assert "the largest of 2" in " ".join(t.get_text() for t in ax.texts)
    one = static.new_figure(THEME).axes[0]
    lake_abacus_comparison.draw(run, one, THEME, station="lake:tarn")
    assert "Lake tarn" in " ".join(t.get_text() for t in one.texts)
    with pytest.raises(FigureNotApplicable, match="named 'nowhere'"):
        lake_abacus_comparison.draw(run, ax, THEME, station="lake:nowhere")
