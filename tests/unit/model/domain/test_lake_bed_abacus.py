"""The lake bed is mapped onto the abacus hypsometry, and flooded back into one."""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.model.domain.lake_bed_abacus import reconcile_bed_to_abacus, simulate_abacus
from tests._helpers.lake_bed_cases import nse


def _reconcile(beds, areas, stage, sarea):
    beds, areas = dict(enumerate(beds)), dict(enumerate(areas))
    return reconcile_bed_to_abacus(bed_by_cell=beds, area_by_cell=areas, abacus_stage=stage, abacus_sarea=sarea)  # fmt: skip


def test_a_prismatic_abacus_carves_a_flat_bottom_at_its_lowest_stage() -> None:
    carved, info = _reconcile(range(40), [1000.0] * 40, [91.0, 93.0, 95.0, 97.0, 99.0], [4e4] * 5)
    assert np.allclose(list(carved.values()), 91.0)
    assert info["area_scale"] == pytest.approx(1.0)


def test_the_carved_bed_floods_back_into_the_target_abacus() -> None:
    """Area grows linearly with stage (a cone), 200 cells of 1 m2."""
    stage = np.linspace(0.0, 10.0, 51)
    sarea = 200.0 * stage / 10.0
    carved, info = _reconcile(range(200), [1.0] * 200, stage, sarea)
    sim = simulate_abacus(
        bed_by_cell=carved, area_by_cell=dict.fromkeys(range(200), 1.0), stages=stage
    )
    assert info["area_scale"] == pytest.approx(1.0)
    assert np.max(np.abs(sim["sarea"] - sarea)) <= 2.0  # one cell of granularity
    assert nse(sim["volume"], 200.0 * stage**2 / 20.0) > 0.999


def test_a_footprint_off_the_abacus_area_is_stretched_onto_it_and_warned_about() -> None:
    """The remap scales the abacus area axis onto the mesh footprint."""
    with pytest.warns(RuntimeWarning, match="area_scale=2.000"):
        carved, info = _reconcile([0.0, 1.0], [1.0, 1.0], [0.0, 1.0], [0.0, 1.0])
    assert info["area_scale"] == pytest.approx(2.0)
    assert list(carved.values()) == pytest.approx([0.25, 0.75])


def test_a_cell_without_a_bed_takes_the_median_depth() -> None:
    carved, info = _reconcile([0.0, np.nan, 2.0], [1.0] * 3, [0.0, 3.0], [0.0, 3.0])
    assert info["n_bed_filled"] == 1.0
    assert carved[1] == pytest.approx(1.5)
    assert carved[0] < carved[1] < carved[2]


@pytest.mark.parametrize(
    ("sarea", "expected"),
    [
        pytest.param([0.0, 1.0, 4.0], 1.0, id="no_plateau"),
        pytest.param([0.0, 1.0, 1.0, 4.0], 1.0, id="plateau", marks=pytest.mark.xfail(
            strict=True, reason="_sarea_inverse returns the upper edge of a plateau its target "
            "area equals, while its docstring promises the lower edge")),
    ],
)  # fmt: skip
def test_a_cell_whose_area_reaches_a_stage_exactly_gets_that_stage(sarea, expected) -> None:
    """Two cells of 2 m2: the first one's mid area is 1 m2, an abacus row."""
    carved, _info = _reconcile([0.0, 1.0], [2.0, 2.0], np.arange(len(sarea), dtype=float), sarea)
    assert carved[0] == pytest.approx(expected)


def test_flooding_two_cells_gives_the_analytic_volume_and_area() -> None:
    sim = simulate_abacus(
        bed_by_cell={0: 0.0, 1: 5.0}, area_by_cell={0: 100.0, 1: 100.0}, stages=[0.0, 5.0, 10.0]
    )
    assert sim["sarea"].tolist() == [0.0, 100.0, 200.0]
    assert sim["volume"].tolist() == [0.0, 500.0, 1500.0]


@pytest.mark.parametrize(
    ("beds", "areas", "stage", "sarea", "match"),
    [
        ([], [], [0.0, 1.0], [0.0, 1.0], "no lake cells"),
        ([0.0], [1.0], [0.0], [1.0], ">= 2 aligned"),
        ([0.0], [1.0], [0.0, 1.0], [1.0], ">= 2 aligned"),
        ([0.0], [1.0], [1.0, 1.0], [0.0, 1.0], "strictly increasing"),
        ([0.0], [1.0], [0.0, 1.0], [1.0, 0.0], "non-decreasing"),
        ([0.0], [0.0], [0.0, 1.0], [0.0, 1.0], "areas must be positive"),
        ([np.nan], [1.0], [0.0, 1.0], [0.0, 1.0], "no finite"),
        ([0.0], [1.0], [0.0, 1.0], [0.0, 0.0], "top sarea must be positive"),
    ],
)
def test_a_bed_or_an_abacus_the_remap_cannot_use_is_refused(beds, areas, stage, sarea, match):
    with pytest.raises(ValueError, match=match):
        _reconcile(beds, areas, stage, sarea)


def test_flooding_no_cell_is_refused() -> None:
    with pytest.raises(ValueError, match="no lake cells"):
        simulate_abacus(bed_by_cell={}, area_by_cell={}, stages=[0.0])
