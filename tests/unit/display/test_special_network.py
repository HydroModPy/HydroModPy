"""The four network and SFR special figures on small subjects whose numbers are known by hand."""

from __future__ import annotations

from types import SimpleNamespace

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import LineString

from hydromodpy.catchment.algorithms.hydrographic_network_comparison import (
    compare_hydrographic_networks,
)
from hydromodpy.display import static
from hydromodpy.display.special import (
    flow_directions,
    network_comparison,
    observed_network_heads,
    sfr_longitudinal_profile,
)
from hydromodpy.display.subject import FigureNotApplicable
from hydromodpy.display.theme import THEMES
from tests._helpers.sealed_runs import sealed_search
from tests.unit.display._network_comparison_run import (
    CELL_M,
    NX,
    NY,
    comparison_run,
)

THEME = THEMES["default"]


def axes():
    return static.new_figure(THEME).axes[0]


def grid(**knobs):
    """The comparison grid, with what ``read_mesh`` asks of a run and the grid does not hold."""
    run = comparison_run(**knobs)
    run.mesh.cell_areas = lambda: np.full(NX * NY, CELL_M**2)
    run.n_layers, run.catchment_mask = 1, np.ones(NX * NY, dtype=bool)
    run.available_hydrographic_network_roles = lambda: ["reference"]
    return run


def sfr_subject(stage=True, shares=None):
    """Reaches 1 (100 m) and 2 (150 m) join at 3, which flows to 4 and, with shares, to 5 too."""
    ids = [f"n:{i}" for i in (1, 2, 3, 4, 5)]
    reaches = pd.DataFrame({"reach_id": ids, "network_id": "n", "reach": [1, 2, 3, 4, 5]})
    reaches["cell2d"], reaches["rtp"] = range(5), [10.0, 9.0, 8.0, 7.0, 6.0]
    reaches["rlen"], reaches["downstream"] = [100.0, 150, 100, 100, 100], [[3], [3], [4, 5], [], []]
    if shares is not None:
        reaches["ustrf"] = [1.0, 1.0, 1.0, *shares]
    rows = [("simulated", "stage", i, t, 10.0 + t) for i in ids for t in (0, 1)]
    series = pd.DataFrame(rows, columns=["source", "variable", "station_id", "timestep", "value"])
    tables = {"sfr_reaches": reaches, "timeseries": series if stage else series[:0]}
    return SimpleNamespace(
        name="sfr", table=tables.__getitem__, has_field=lambda v, **_: True,
        field=lambda v, time=0, **_: np.array([10.5, 9.5, 8.5, 7.5, 6.5]) + time,
        periods=SimpleNamespace(step_at=int),
    )  # fmt: skip


@pytest.mark.parametrize(
    ("shares", "outlet_bed", "rule"),
    [(None, 7.0, False), ((0.3, 0.7), 6.0, True)],
)
def test_sfr_profile_follows_the_larger_flow_share_else_the_longest_path(shares, outlet_bed, rule):
    sfr_longitudinal_profile.draw(sfr_subject(shares=shares), ax := axes(), THEME)
    note = ax.texts[0].get_text()
    assert "3 of 5 reaches, 0.3 of 0.6 km" in note and ("larger flow share" in note) == rule
    bed = next(line for line in ax.lines if line.get_label() == "Streambed top")
    np.testing.assert_allclose(bed.get_xdata(), [0.275, 0.15, 0.05])
    np.testing.assert_allclose(bed.get_ydata(), [9.0, 8.0, outlet_bed])
    sfr_longitudinal_profile.draw(sfr_subject(), one := axes(), THEME, time=1)
    assert (len(ax.collections), len(one.collections)) == (4, 2)


def test_heads_figure_marks_the_one_head_the_sealed_area_keeps():
    run = grid()
    streams = {"support": "network", "model": {"seepage_threshold": 0.0}}
    streams["map"] = {"complete": "data.hydrography", "drawn_by": "heads"}
    run.dir = sealed_search({"outputs": {"streams": streams}})
    observed_network_heads.draw(run, ax := axes(), THEME)
    assert ax.get_title() == "Heads: 1 traced, 0 lost"
    assert ax.get_legend_handles_labels()[1][:2] == ["Traced (3 cells)", "Mapped network"]
    assert "Head kept (1)" in ax.get_legend_handles_labels()[1]


def pair_run(*, with_generated=True):
    x = (run := grid()).outlet[0]
    near = LineString([(x + 10.0, 0.1 * CELL_M), (x + 10.0, (NY - 0.1) * CELL_M)])
    nets = {"reference": run.hydrographic_network("reference")}
    if with_generated:
        nets["generated"] = gpd.GeoDataFrame(
            geometry=[near, LineString([(x + 4000, 0), (x + 4000, 100)])], crs=run.mesh.crs
        )
    run.available_hydrographic_network_roles = lambda: list(nets)
    run.has_hydrographic_network = lambda role="generated": role in nets
    run.hydrographic_network = lambda role="generated": nets[role]
    run.hydrographic_network_comparison = lambda **kw: compare_hydrographic_networks(
        nets["reference"], nets["generated"], **kw
    )
    return run


def test_comparison_colours_matched_missing_and_extra_lines():
    network_comparison.draw(pair_run(), ax := axes(), THEME)
    held = ax.get_legend_handles_labels()[1]
    assert held[0] == "Buffer, 50 m"
    assert {"Mapped, matched (1)", "Mapped only (0)", "Generated only (1)"} <= set(held)


def test_flow_directions_draw_one_arrow_per_routed_cell_and_ring_the_raised_one():
    top = grid().mesh.topography.copy()
    top[NX + 1] = -50.0
    flow_directions.draw(grid(topography=top), ax := axes(), THEME)
    arrows = next(c for c in ax.collections if hasattr(c, "U"))
    assert len(arrows.get_offsets()) == NX * NY - 1
    assert "Raised by the descent (1)" in ax.get_legend_handles_labels()[1]


@pytest.mark.parametrize(
    ("module", "subject", "message"),
    [
        (sfr_longitudinal_profile, lambda: sfr_subject(stage=False), "no SFR stage series"),
        (observed_network_heads, lambda: grid(with_release=False), "release_flux"),
        (network_comparison, lambda: pair_run(with_generated=False), "generated"),
        (flow_directions, lambda: grid(topography=np.full(NX * NY, np.nan)), "usable"),
    ],
)
def test_a_run_without_the_data_is_refused(module, subject, message):
    with pytest.raises(FigureNotApplicable, match=message):
        module.draw(subject(), axes(), THEME)
