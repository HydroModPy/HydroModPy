"""The figures of a comparison of runs: the difference drawn is the difference of the values."""

from __future__ import annotations

import matplotlib
import numpy as np
import pytest

import hydromodpy as hmp
from hydromodpy.display import run_comparison
from hydromodpy.results.run.view import Run
from tests.unit.display._stored_run import HEAD_TOP, N_CELLS, write_run


@pytest.fixture(scope="module")
def two_runs(tmp_path_factory) -> list[Run]:
    project = tmp_path_factory.mktemp("two_runs") / "proj"
    write_run(project, "base")
    write_run(project, "warm", head_shift=2.0)
    store = hmp.open(project).store
    return [store["base"], store["warm"]]


def test_a_map_shows_the_hand_difference(two_runs, tmp_path, monkeypatch):
    shown = []
    real = run_comparison.map_frame.draw
    monkeypatch.setattr(
        run_comparison.map_frame, "draw", lambda ax, d, t: (shown.append(d), real(ax, d, t))
    )
    before = dict(matplotlib.rcParams)

    run_comparison.draw_maps(
        [HEAD_TOP - 1.0, HEAD_TOP + 1.0], two_runs, "watertable_elevation", "last", tmp_path / "m"
    )

    np.testing.assert_allclose(shown[1].table["value"], np.full(N_CELLS, 2.0))
    assert shown[1].scale == "diverging" and shown[1].limits == (-2.0, 2.0)
    assert (tmp_path / "m.png").exists() and dict(matplotlib.rcParams) == before


def test_another_mesh_is_refused(two_runs, tmp_path):
    with pytest.raises(ValueError, match="cannot be subtracted"):
        run_comparison.draw_maps(
            [np.zeros(N_CELLS), np.zeros(N_CELLS - 1)], two_runs, "head", "last", tmp_path / "x"
        )
