"""The four special figures of series and particles on small subjects."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace

import matplotlib.dates as mdates
import numpy as np
import pandas as pd
import pytest
from matplotlib.collections import LineCollection, PolyCollection
from matplotlib.colors import Normalize

import hydromodpy as hmp
from hydromodpy.display import overlays, static, variables
from hydromodpy.display.special import (
    ensemble_band,
    particle_tracks,
    recession,
    records,
    residence_time_distribution,
)
from hydromodpy.display.subject import FigureNotApplicable
from hydromodpy.display.theme import THEMES
from hydromodpy.results.catalog.indexer import rebuild_index
from hydromodpy.results.derive.recession import brutsaert_nieber_coefficient
from hydromodpy.results.run import particles as particle_module
from hydromodpy.results.run.group import RunSet
from hydromodpy.results.storage.attempt import close_sealed_attempt
from hydromodpy.results.storage.sealing import seal_completed
from tests._helpers.run_builders import GAUGE, score
from tests._helpers.run_stores import open_run_store
from tests.unit.display._stored_run import X0, Y0, ZONE_AREA

THEME = THEMES["default"]
DAYS = pd.date_range("2001-01-02", periods=60, freq="D")


def write_daily(project, name, values):
    store = open_run_store(
        project, name, n_cells=1, n_timesteps=len(values), period_start=datetime(2001, 1, 1, tzinfo=UTC),
        period_end=datetime(2001, 3, 3, tzinfo=UTC), time_unit="day",
    )  # fmt: skip
    index = DAYS[: len(values)]
    store.write_time(store.sim_id, index.values.astype("datetime64[s]").astype("int64"))
    for station in ("catchment", GAUGE):
        store.write_timeseries(store.sim_id, station, "discharge", pd.Series(values, index=index), unit="m3/s")  # fmt: skip
    score(store, 0.8)
    seal_completed(store)
    close_sealed_attempt(store.run_dir)


def drawn(module, subject, **kwargs):
    ax = static.new_figure(THEME).axes[0]
    module.draw(subject, ax, THEME, **kwargs)
    return ax


class Held:
    """A run with some of its reads replaced, the others going to the run itself."""

    def __init__(self, run, **replaced):
        self._run = run
        self.__dict__.update(replaced)

    def __getattr__(self, name):
        return getattr(self._run, name)


class Group(RunSet):
    def __init__(self, runs):
        self._runs, self._sim_ids = runs, [run.sim_id for run in runs]

    def __iter__(self):
        return iter(self._runs)


def test_the_recession_fit_finds_the_exponent_of_a_boussinesq_recession(tmp_path):
    flow = (1.0 + 0.02 * np.arange(60)) ** -2.0
    write_daily(tmp_path / "p", "boussinesq", flow)
    rebuild_index(tmp_path / "p")
    ax = drawn(recession, hmp.open(tmp_path / "p").store["boussinesq"])
    fit = ax.lines[0]
    slope = np.polyfit(np.log(fit.get_xdata()), np.log(fit.get_ydata()), 1)[0]
    assert slope == pytest.approx(1.5, abs=0.05)
    assert len(ax.lines) == 3 and ax.get_xscale() == "log"
    assert "no hydraulic conductivity" in ax.texts[0].get_text()  # the run stores no aquifer


def test_the_boussinesq_line_takes_k_porosity_area_and_length_from_the_run(stored_run, monkeypatch):
    def field(name, **kw):
        return np.full((2, 12), 2.0e-5 if name == "hydraulic_conductivity" else 0.1)

    monkeypatch.setattr(recession, "_stream_length", lambda run: 4000.0)
    held = Held(stored_run, has_field=lambda name, **kw: True, field=field)
    a, missing = recession._boussinesq(held)
    expected = brutsaert_nieber_coefficient(k=2.0e-5 * 86400, porosity=0.1, stream_length=4000.0, area=ZONE_AREA)  # fmt: skip
    assert (missing, a) == ([], pytest.approx(expected))


def test_the_boussinesq_line_is_rescaled_to_the_display_unit():
    assert recession._in_display(3.0, 21600.0) == pytest.approx(6.0)  # sqrt(86400 / 21600) = 2


def test_the_ensemble_band_is_the_10_to_90_percent_quantiles_of_the_runs_at_each_stamp(tmp_path):
    base = np.linspace(1.0, 2.0, 10)
    for name, scale in (("a", 1.0), ("b", 1.5), ("c", 0.8)):
        write_daily(tmp_path / "p", name, base * scale * (1 + 0.1 * (name == "b") * np.arange(10)))
    rebuild_index(tmp_path / "p")
    store = hmp.open(tmp_path / "p").store
    ax = drawn(ensemble_band, Group([store[name] for name in "abc"]))
    rows = np.array([base[4] * 1.0, base[4] * 1.5 * 1.4, base[4] * 0.8])
    path = ax.collections[0].get_paths()[0].vertices
    # The run set reads stamps as period starts, so stamp 4 is day 4 of the record.
    at = path[np.isclose(path[:, 0], mdates.date2num(DAYS[3]))][:, 1]
    assert (at.min(), at.max()) == pytest.approx(tuple(np.quantile(rows, [0.1, 0.9])))
    assert ax.lines[0].get_ydata()[4] == pytest.approx(np.median(rows))


def with_particles(monkeypatch, run, years, porosity=0.1, starts=None):
    """Give the run one two-step pathline per travel time, as ``read_particle_tracks`` does.

    ``starts`` gives the release point of each line, else they are far from every cell.
    """
    starts = starts or [(100.0 * i, 0.0) for i in range(len(years))]
    tracks = [
        np.array([[x, y, 0.0, 0.0], [x + 50.0, y + 10.0, 0.0, t * 365.25]])
        for (x, y), t in zip(starts, years, strict=True)
    ]
    monkeypatch.setattr(particle_module, "read_particle_tracks", lambda run: tracks)
    monkeypatch.setattr(particle_module, "particle_time_to_days", lambda run: 1.0)
    budget = pd.DataFrame({"timestep": range(4), "component": "constant_head", "flux_out": 1e-3})
    stored = porosity is not None

    def field(name, **kw):
        return np.full((2, 12), porosity) if name == "porosity" else run.field(name, **kw)

    return Held(run, budget=lambda zone_id=None: budget,
                has_field=lambda name, **kw: stored if name == "porosity" else run.has_field(name, **kw),
                field=field)  # fmt: skip


def test_the_survival_step_holds_every_travel_time_and_ends_at_the_longest(stored_run, monkeypatch):
    ax = drawn(
        residence_time_distribution, with_particles(monkeypatch, stored_run, [0.0, *range(1, 11)])
    )
    assert np.median(ax.lines[0].get_xdata()) == pytest.approx(5.5)
    assert ax.get_yscale() == "log" and len(ax.lines) == 3
    turnover = [
        float(
            drawn(
                residence_time_distribution, with_particles(monkeypatch, stored_run, [1.0, 2.0], p)
            )
            .lines[2]
            .get_label()
            .split(", ")[1]
        )  # fmt: skip
        for p in (0.1, 0.2)
    ]
    assert turnover[1] == pytest.approx(2 * turnover[0], rel=0.01)  # pore volume follows porosity
    with pytest.raises(FigureNotApplicable, match="porosity"):
        drawn(
            residence_time_distribution, with_particles(monkeypatch, stored_run, [1.0, 2.0], None)
        )


def test_the_particle_tracks_colour_each_line_by_the_age_of_the_water(stored_run, monkeypatch):
    years = [0.0, *np.arange(1.0, 11.0)]
    ax = drawn(particle_tracks, with_particles(monkeypatch, stored_run, years))
    coloured = next(c for c in ax.collections if c.get_array() is not None)
    grey = [c for c in ax.collections if isinstance(c, LineCollection) and c is not coloured]
    ages = np.sort(np.asarray(coloured.get_array()))
    # One piece per two-step path: its colour is the age at its end, the travel time.
    assert set(ages) <= set(years[1:]) and isinstance(coloured.norm, Normalize)
    assert (coloured.norm.vmin, coloured.norm.vmax) == pytest.approx((0.0, np.percentile(ages, 99)))
    outside = sum(len(c.get_segments()) for c in grey if c.get_label() == "Outside the catchment")
    assert len(ages) + outside == 10  # the particle that never moved has no line
    assert ax.get_title(loc="right").startswith("10 pathlines")
    assert ax.get_title(loc="left").startswith("Age of the water along the pathlines")


def test_the_particle_tracks_draw_thin_lines_over_the_map_of_a_variable(stored_run, monkeypatch):
    run = with_particles(monkeypatch, stored_run, np.arange(1.0, 11.0))
    ax = drawn(particle_tracks, run, variable=["head"], time=0)
    cells = next(c for c in ax.collections if isinstance(c, PolyCollection))
    assert len(cells.get_paths()) == 12 and len(ax.figure.axes) == 2  # the map and its bar
    assert ax.get_title(loc="left").startswith("Hydraulic head")
    assert ax.get_title(loc="right") == "January 2001, 10 pathlines"
    lines = [c for c in ax.collections if isinstance(c, LineCollection)]
    assert any(len(c.get_segments()) == 10 and c.get_array() is None for c in lines)
    with pytest.raises(FigureNotApplicable, match="over one variable"):
        drawn(particle_tracks, run, variable=["head", "topography"])


@pytest.mark.parametrize(
    "module", [recession, residence_time_distribution, particle_tracks, ensemble_band]
)
def test_a_subject_without_the_data_is_not_applicable(stored_run, module):
    subject = Group([stored_run]) if module is ensemble_band else stored_run
    with pytest.raises(FigureNotApplicable):
        drawn(module, subject)


INSIDE = (X0 + 250.0, Y0 + 250.0)
OUTSIDE = (X0 + 250.0, Y0 + 1250.0)


@pytest.mark.parametrize(
    ("starts", "grey", "coloured", "note"),
    [
        ([INSIDE] * 3 + [OUTSIDE] * 2, 2, 3, "3 from the catchment in colour"),
        ([OUTSIDE] * 4, 0, 4, None),
    ],
)
def test_the_particle_tracks_grey_the_lines_released_outside_the_catchment(
    stored_run, monkeypatch, starts, grey, coloured, note
):
    run = with_particles(monkeypatch, stored_run, np.arange(1.0, len(starts) + 1), starts=starts)
    ax = drawn(particle_tracks, run)
    lines = [c for c in ax.collections if isinstance(c, LineCollection)]
    outside = [c for c in lines if c.get_label() == "Outside the catchment"]
    assert sum(len(c.get_segments()) for c in outside) == grey
    assert len(next(c for c in lines if c.get_array() is not None).get_segments()) == coloured
    assert (note in ax.get_title(loc="right")) if note else "catchment" not in ax.get_title(loc="right")  # fmt: skip
    assert ("Outside the catchment" in ax.get_legend_handles_labels()[1]) == bool(grey)


def test_the_particle_tracks_thin_out_a_crowd_of_lines_and_say_so(stored_run, monkeypatch):
    monkeypatch.setattr(particle_tracks, "MAX_LINES", 3)
    run = with_particles(monkeypatch, stored_run, np.arange(1.0, 11.0), starts=[INSIDE] * 10)
    ax = drawn(particle_tracks, run)
    coloured = next(c for c in ax.collections if c.get_array() is not None)
    assert len(coloured.get_segments()) == 3  # one in 4 of the 10 lines
    assert ax.get_title(loc="right") == "10 pathlines, one in 4 drawn"


def test_the_particle_tracks_over_a_variable_say_how_many_lines_are_drawn(stored_run, monkeypatch):
    monkeypatch.setattr(overlays, "MAX_PATHLINES", 4)
    run = with_particles(monkeypatch, stored_run, np.arange(1.0, 11.0), starts=[INSIDE] * 10)
    ax = drawn(particle_tracks, run, variable="head", time=0)
    assert ax.get_title(loc="right").endswith("10 pathlines, one in 3 drawn")


def decaying(index, values):
    return pd.Series(values, index=index, dtype=float)


def test_the_recession_draws_the_boussinesq_line_and_skips_the_fit_of_a_short_record(
    stored_run, monkeypatch
):
    days = pd.date_range("2001-01-01", periods=5, freq="D")
    simulated = decaying(days, [5.0, 4.0, 3.0, 2.0, 1.0])
    monkeypatch.setattr(recession, "_stream_length", lambda run: 4000.0)
    monkeypatch.setattr(recession, "read_observed", lambda *a, **k: decaying(days, [5, 5, 5, 5, 4]))
    run = Held(stored_run, timeseries=lambda variable, station=None: simulated,
               has_field=lambda name, **kw: True, field=lambda name, **kw: np.full((2, 12), 0.1))  # fmt: skip
    ax = drawn(recession, run)
    labels = ax.get_legend_handles_labels()[1]
    assert sum(label.startswith("Boussinesq") for label in labels) == 1
    assert not any(label.startswith("observed") for label in labels)  # one falling step, no fit
    assert any(label.startswith("simulated, fitted b") for label in labels)
    assert not ax.texts


def test_the_recession_refuses_a_run_without_a_discharge_series(stored_run):
    def absent(variable, station=None):
        raise KeyError(variable)

    with pytest.raises(FigureNotApplicable, match="stores no 'discharge' series"):
        drawn(recession, Held(stored_run, timeseries=absent))


def test_the_boussinesq_line_names_a_field_that_is_empty_on_the_catchment(stored_run):
    held = Held(stored_run, has_field=lambda name, **kw: True,
                field=lambda name, **kw: np.full((2, 12), np.nan))  # fmt: skip
    coefficient, missing = recession._boussinesq(held)
    assert coefficient is None
    assert missing == ["hydraulic conductivity", "specific yield", "stream network"]


def test_the_ensemble_band_refuses_an_empty_set_and_a_lone_run(stored_run):
    with pytest.raises(FigureNotApplicable, match="run set is empty"):
        drawn(ensemble_band, Group([]))
    with pytest.raises(FigureNotApplicable, match="Only 0 of the 2 runs"):
        drawn(ensemble_band, Group([stored_run, stored_run]), station="zone:nowhere")


def test_the_ensemble_band_draws_the_record_over_runs_with_numbered_stamps(stored_run, monkeypatch):
    stamps = pd.RangeIndex(1, 5, name="period")
    table = {0: [1.0, 2.0, 3.0, 4.0], 1: [2.0, 3.0, 4.0, 5.0], 2: [3.0, 4.0, 5.0, 6.0]}
    runs = [Held(stored_run, sim_id=str(n)) for n in table]
    seen = iter(table.values())
    monkeypatch.setattr(ensemble_band, "read_series", lambda run, name, station=None: pd.Series(next(seen), index=stamps))  # fmt: skip
    monkeypatch.setattr(ensemble_band, "read_observed", lambda run, name, station=None: pd.Series([2.0, np.nan, 4.0, 5.0], index=stamps))  # fmt: skip
    ax = drawn(ensemble_band, Group(runs), station="gauge")
    assert ax.get_xlabel() == "Period"
    assert ax.lines[0].get_ydata().tolist() == pytest.approx(
        variables.to_display("discharge", np.median(list(table.values()), axis=0)).tolist()
    )
    assert len(ax.lines) == 2  # the median and the record
    assert ax.lines[1].get_ydata().tolist() == [
        2.0,
        4.0,
        5.0,
    ]  # the stamp without a value is dropped


def test_the_survival_step_refuses_a_mesh_without_layer_interfaces(stored_run, monkeypatch):
    real = residence_time_distribution.read_mesh
    monkeypatch.setattr(residence_time_distribution, "read_mesh", lambda run: replace(real(run), interfaces=None))  # fmt: skip
    with pytest.raises(FigureNotApplicable, match="no layer interfaces"):
        drawn(residence_time_distribution, with_particles(monkeypatch, stored_run, [1.0, 2.0]))


def test_the_acceptable_cost_ring_needs_a_threshold_and_a_cost_under_it():
    ax = static.new_figure(THEME).axes[0]
    x, ys, cost = np.arange(3.0), [np.arange(3.0)], [3.0, 2.0, 1.0]
    records.ring_acceptable(ax, x, ys, cost, None, THEME)
    records.ring_acceptable(ax, x, ys, cost, 0.5, THEME)
    assert not ax.collections
    records.ring_acceptable(ax, x, ys, cost, 2.0, THEME)
    assert ax.collections[0].get_offsets().tolist() == [[1.0, 1.0], [2.0, 2.0]]
    assert ax.collections[0].get_label() == "Cost under 2"


def test_a_station_that_is_asked_for_is_returned_without_reading_the_scores():
    assert records.scored_station(None, "discharge", "gauge") == "gauge"


def estimates_subject(rows):
    table = pd.DataFrame(rows, columns=["method", "station", "year", "quantity", "value", "unit"])
    return SimpleNamespace(name="r", table=lambda name: table)


def test_recharge_estimates_draws_one_column_per_method_and_the_run_last():
    from hydromodpy.display.special import recharge_estimates

    rows = [
        ("run", None, 2016, "recharge", 300.0, "mm"),
        ("run", None, 2017, "recharge", 250.0, "mm"),
        ("eckhardt", None, 2016, "recharge", 280.0, "mm"),
        ("eckhardt", None, 2017, "recharge", 240.0, "mm"),
        ("turc", None, 2016, "effective_rainfall", 410.0, "mm"),
        ("wtf", "PZ1", 2016, "recharge", 200.0, "mm"),
        ("eckhardt", None, None, "bfi_max", 0.8, "-"),
    ]
    ax = static.new_figure(THEMES["default"]).axes[0]

    recharge_estimates.draw(estimates_subject(rows), ax, THEMES["default"])

    labels = [tick.get_text() for tick in ax.get_xticklabels()]
    assert labels == ["eckhardt", "turc\n(effective rain)", "wtf\nPZ1", "run"]


def test_recharge_estimates_without_yearly_rows_is_not_applicable():
    from hydromodpy.display.special import recharge_estimates
    from hydromodpy.display.subject import FigureNotApplicable

    ax = static.new_figure(THEMES["default"]).axes[0]
    with pytest.raises(FigureNotApplicable, match="no yearly value"):
        recharge_estimates.draw(
            estimates_subject([("closing_factor", None, None, "factor", 1.1, "-")]),
            ax,
            THEMES["default"],
        )


def test_water_balance_loop_joins_the_mean_months_in_calendar_order():
    from hydromodpy.display.special import water_balance_loop

    rows = []
    for year in (2016, 2017):
        for month in range(1, 13):
            wet = np.cos(2 * np.pi * (month - 1) / 12)
            rows.append(("water_balance", None, year, month, "rain_minus_etr", 40 + 60 * wet, "mm"))
            rows.append(
                ("water_balance", None, year, month, "gauged_discharge", 40 + 30 * wet, "mm")
            )
    table = pd.DataFrame(
        rows, columns=["method", "station", "year", "month", "quantity", "value", "unit"]
    )
    ax = static.new_figure(THEMES["default"]).axes[0]

    water_balance_loop.draw(
        SimpleNamespace(name="r", table=lambda name: table), ax, THEMES["default"]
    )

    loop = ax.lines[0]
    assert len(loop.get_xdata()) == 13  # twelve months, closed on January
    assert loop.get_ydata()[0] == pytest.approx(100.0)


def signals_subject(methods: tuple[str, ...] = ("fao56", "sim2", "run")) -> SimpleNamespace:
    """Two years of monthly rain, ETP, and the recharge and runoff of each method."""
    rows = []
    for year in (2016, 2017):
        for month in range(1, 13):
            wet = 1.0 + np.cos(2 * np.pi * (month - 1) / 12)
            rows.append(("input", None, year, month, "precipitation", 40 + 30 * wet, "mm"))
            rows.append(("input", None, year, month, "etp", 70 - 30 * wet, "mm"))
            for rank, method in enumerate(methods):
                rows.append((method, None, year, month, "recharge", (rank + 1) * 10 * wet, "mm"))
                rows.append((method, None, year, month, "runoff", rank * wet, "mm"))
    table = pd.DataFrame(
        rows, columns=["method", "station", "year", "month", "quantity", "value", "unit"]
    )
    return SimpleNamespace(name="r", table=lambda name: table)


def test_recharge_signals_stacks_weather_recharge_and_runoff_with_the_run_last():
    from hydromodpy.display.special import recharge_signals

    ax = static.new_figure(THEMES["default"]).axes[0]

    recharge_signals.draw(signals_subject(), ax, THEMES["default"])

    weather, recharge, runoff = ax.child_axes
    assert [line.get_label() for line in recharge.lines] == ["fao56", "sim2", "run"]
    assert recharge.lines[-1].get_linestyle() == "--"
    assert len(weather.patches) == 24
    # Each month is held to its end: 24 months and the closing edge.
    assert len(runoff.lines[0].get_xdata()) == 25


def test_recharge_regime_draws_the_mean_month_of_each_method():
    from hydromodpy.display.special import recharge_regime

    ax = static.new_figure(THEMES["default"]).axes[0]

    recharge_regime.draw(signals_subject(), ax, THEMES["default"])

    weather, recharge, runoff = ax.child_axes
    fao56 = recharge.lines[0]
    assert list(fao56.get_xdata()) == list(range(1, 13))
    assert fao56.get_ydata()[0] == pytest.approx(20.0)
    assert len(runoff.lines) == 3


def test_a_run_without_monthly_signals_has_no_signal_figure():
    from hydromodpy.display.special import recharge_signals

    table = pd.DataFrame(
        [("eckhardt", None, 2016, None, "recharge", 250.0, "mm")],
        columns=["method", "station", "year", "month", "quantity", "value", "unit"],
    )
    ax = static.new_figure(THEMES["default"]).axes[0]
    with pytest.raises(FigureNotApplicable, match="holds no monthly signal"):
        recharge_signals.draw(
            SimpleNamespace(name="r", table=lambda name: table), ax, THEMES["default"]
        )
