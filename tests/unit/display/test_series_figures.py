"""Time-series figures: flux depth by zone, shading before the scoring window."""

from __future__ import annotations

import datetime
from types import SimpleNamespace

import matplotlib.dates as mdates
import numpy as np
import pandas as pd
import pytest

from hydromodpy.display.figures.flux_timeseries import FluxTimeseries
from hydromodpy.display.figures.hydrograph import Hydrograph
from hydromodpy.display.figures.hydrograph_sim_obs import HydrographSimObs
from hydromodpy.display.figures.lake_level_sim_obs import LakeStageSimObs
from hydromodpy.display.figures.piezo_timeseries_sim_obs import PiezoTimeseriesSimObs
from hydromodpy.display.figures.residuals import Residuals
from hydromodpy.display.figures.sfr_reach_timeseries import SfrReachTimeseries
from hydromodpy.results.run.descent import StoredBasin
from tests._helpers.ugrid_meshes import quad_mesh

# A flux drawn in mm/period is divided by the area of the zone its rows sum over.
#
# The ``catchment`` row of the budget is the water of the whole faces of the basin
# of D. Divided by the whole domain it came out too small by the ratio of the two
# areas. The domain row keeps the domain area, and a catchment row on a run that
# stores no basin has no area to divide by.

CELL = 100.0


NROW, NCOL = 4, 4


BASIN = np.zeros(NROW * NCOL, dtype=bool)


BASIN[[0, 1, 4, 5, 8, 9]] = True


DOMAIN_AREA = NROW * NCOL * CELL**2


BASIN_AREA = int(BASIN.sum()) * CELL**2


EDGES = pd.date_range("2000-01-01", periods=4, freq="D")


DAY = 86400.0


DOMAIN_RECHARGE = np.array([4.0, 3.0, 2.0])


BASIN_RECHARGE = np.array([1.5, 1.0, 0.5])


pytestmark = pytest.mark.usefixtures("mpl")


def _budget(zones: tuple[str, ...]) -> pd.DataFrame:
    rows = []
    for zone in zones:
        flux = DOMAIN_RECHARGE if zone == "0" else BASIN_RECHARGE
        rows += [
            {"component": "recharge", "zone_id": zone, "timestep": t, "flux_in": v, "flux_out": 0.0}
            for t, v in enumerate(flux)
        ]
    return pd.DataFrame(rows)


def _run(zones: tuple[str, ...], *, basin: np.ndarray | None = BASIN) -> SimpleNamespace:
    vertices, connectivity = quad_mesh(NROW, NCOL, cell_size=CELL)
    stored = (
        None
        if basin is None
        else StoredBasin(mask=basin, area_m2=float(basin.sum()) * CELL**2, rule="near_point")
    )
    return SimpleNamespace(
        sim_id="sim-zone",
        name="zone",
        periods=SimpleNamespace(edges=EDGES),
        mesh=SimpleNamespace(vertices=vertices, face_node_connectivity=connectivity),
        descent=SimpleNamespace(stored_basin=lambda: stored),
        budget=lambda: _budget(zones),
    )


def _flux_depth_drawn(run, mpl, **options):
    _, ax = mpl.subplots()
    FluxTimeseries().render(run, ax, units="mm/period", **options)
    recharge = next(line for line in ax.lines if line.get_label() == "recharge")
    return ax, np.asarray(recharge.get_ydata())[:-1]


def test_the_catchment_row_is_divided_by_the_area_of_the_basin(mpl) -> None:
    ax, depth = _flux_depth_drawn(_run(("0", "catchment")), mpl)

    np.testing.assert_allclose(depth, 1000.0 * DAY * BASIN_RECHARGE / BASIN_AREA)
    assert "over the delineated catchment" in ax.get_ylabel()


def test_the_old_depth_was_too_small_by_the_ratio_of_the_areas(mpl) -> None:
    _, depth = _flux_depth_drawn(_run(("0", "catchment")), mpl)

    over_the_domain = 1000.0 * DAY * BASIN_RECHARGE / DOMAIN_AREA
    np.testing.assert_allclose(over_the_domain / depth, BASIN_AREA / DOMAIN_AREA * np.ones(3))
    assert BASIN_AREA < DOMAIN_AREA


def test_the_domain_row_is_divided_by_the_area_of_the_domain(mpl) -> None:
    ax, depth = _flux_depth_drawn(_run(("0",)), mpl)

    np.testing.assert_allclose(depth, 1000.0 * DAY * DOMAIN_RECHARGE / DOMAIN_AREA)
    assert "over the model domain" in ax.get_ylabel()


def test_the_domain_row_needs_no_stored_basin(mpl) -> None:
    _, depth = _flux_depth_drawn(_run(("0",), basin=None), mpl)

    np.testing.assert_allclose(depth, 1000.0 * DAY * DOMAIN_RECHARGE / DOMAIN_AREA)


def test_a_catchment_row_without_a_stored_basin_has_no_depth(mpl) -> None:
    with pytest.raises(ValueError, match="stores no basin of D"):
        _flux_depth_drawn(_run(("0", "catchment"), basin=None), mpl)


def test_the_flux_in_m3_s_does_not_read_the_area(mpl) -> None:
    _, ax = mpl.subplots()
    run = _run(("0", "catchment"), basin=None)

    FluxTimeseries().render(run, ax)

    recharge = next(line for line in ax.lines if line.get_label() == "recharge")
    np.testing.assert_allclose(np.asarray(recharge.get_ydata())[:-1], BASIN_RECHARGE)


# A series figure shades the period that precedes ``[metrics] window``.
#
# The spin-up is the part of a run before the window it is scored on. Each figure
# that draws a time series of one run reads that window from the run (the score
# it sealed, else the ``[metrics]`` window of its config) and shades what comes
# before it. No figure option names it, and a run without a window shades nothing.

STAMPS = pd.date_range("2011-01-01", periods=10, freq="D")


WINDOW_START = datetime.date(2011, 1, 5)


LABEL = "before the scoring window"


class _Run:
    """A run holding the series of every figure under test."""

    sim_id = "sim-spinup"
    name = "spinup"
    periods = SimpleNamespace(edges=pd.date_range("2010-12-31", periods=11, freq="D"))

    def __init__(self, *, sealed=None, snapshot=None) -> None:
        if sealed is not None:
            self.metrics = pd.DataFrame(
                [
                    {
                        "station": "J1",
                        "variable": "discharge",
                        "metric": "nse",
                        "value": 0.5,
                        "window_start": sealed[0],
                        "window_end": sealed[1],
                        "n_samples": 3,
                        "metric_rule_version": "1",
                    }
                ]
            )
        self.config_snapshot = snapshot

    def has_table(self, table: str) -> bool:
        return True

    def has_field(self, variable: str, **_) -> bool:
        return True

    def stations(self, variable: str) -> list[str]:
        return ["catchment", "net:1"]

    def timeseries(self, variable: str, *, station: str | None = None, **_) -> pd.Series:
        return pd.Series(np.linspace(1.0, 2.0, len(STAMPS)), index=STAMPS)

    def observed(self, variable: str, station: str | None = None, period=None) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "station_id": ["J1"] * len(STAMPS),
                "datetime": STAMPS.shift(-1, freq="D"),
                "value": np.linspace(1.1, 2.1, len(STAMPS)) + 0.05 * (np.arange(len(STAMPS)) % 3),
            }
        )

    def budget(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "component": ["recharge"] * 10,
                "timestep": list(range(10)),
                "flux_in": [1.0] * 10,
                "flux_out": [0.0] * 10,
            }
        )


def _residuals(run):
    return Residuals().plot(run, observed_station="J1").axes[0]


def _drawn(figure_name, run, monkeypatch=None):
    import matplotlib.pyplot as plt

    if figure_name == "residuals":
        return _residuals(run)
    fig, ax = plt.subplots()
    figure = {
        "hydrograph": Hydrograph,
        "hydrograph_sim_obs": HydrographSimObs,
        "piezo": PiezoTimeseriesSimObs,
        "sfr": SfrReachTimeseries,
        "flux": FluxTimeseries,
        "lake_stage": LakeStageSimObs,
    }[figure_name]()
    options = {"piezo": {"station": "obs:P1"}, "sfr": {"variable": "stage"}}.get(figure_name, {})
    if figure_name == "lake_stage":
        from hydromodpy.display.figures import lake_level_sim_obs

        monkeypatch.setattr(lake_level_sim_obs, "_default_lake", lambda sim: "L1")
    figure.render(run, ax, **options)
    return ax


FIGURES = ["hydrograph", "hydrograph_sim_obs", "piezo", "sfr", "flux", "lake_stage", "residuals"]


@pytest.fixture(autouse=True)
def _one_reach(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "hydromodpy.display.figures.sfr_reach_timeseries.sfr_reach_links",
        lambda _run: pd.DataFrame({"reach_id": ["net:1"], "network_id": ["net"], "reach": [1]}),
    )


def _shades(ax):
    return [patch for patch in ax.patches if patch.get_label() == LABEL]


@pytest.mark.parametrize("figure", FIGURES)
def test_a_series_figure_shades_up_to_the_sealed_window_start(figure, monkeypatch) -> None:
    run = _Run(sealed=(WINDOW_START, datetime.date(2011, 1, 8)))

    ax = _drawn(figure, run, monkeypatch)

    (shade,) = _shades(ax)
    assert shade.get_x() + shade.get_width() == pytest.approx(
        mdates.date2num(datetime.datetime(2011, 1, 5))
    )
    assert shade.get_x() == pytest.approx(ax.get_xlim()[0])


@pytest.mark.parametrize("figure", FIGURES)
def test_a_run_without_a_window_shades_nothing(figure, monkeypatch) -> None:
    ax = _drawn(figure, _Run(), monkeypatch)

    assert _shades(ax) == []


def test_the_window_of_the_config_serves_a_run_that_sealed_no_score() -> None:
    snapshot = {"metrics": {"window": {"start": "2011-01-04", "end": "2011-01-09"}}}

    ax = _drawn("hydrograph", _Run(snapshot=snapshot))

    (shade,) = _shades(ax)
    assert shade.get_x() + shade.get_width() == pytest.approx(
        mdates.date2num(datetime.datetime(2011, 1, 4))
    )


def test_a_window_that_starts_with_the_run_shades_nothing() -> None:
    run = _Run(sealed=(datetime.date(2010, 12, 1), datetime.date(2011, 1, 8)))

    assert _shades(_drawn("hydrograph", run)) == []


def test_the_shade_says_what_it_is_in_the_legend() -> None:
    ax = _drawn("hydrograph", _Run(sealed=(WINDOW_START, datetime.date(2011, 1, 8))))

    assert LABEL in [text.get_text() for text in ax.get_legend().get_texts()]
