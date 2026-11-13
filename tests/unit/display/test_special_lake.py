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


def lake_run(project):
    store = open_run_store(project, "lake", n_cells=1, n_timesteps=1)
    store.write_lake_abacus(
        store.sim_id, "pond", stage=STAGE, real_volume=REAL, sim_volume=REAL * 1.1,
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
