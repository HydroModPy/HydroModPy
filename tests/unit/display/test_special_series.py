"""The four special figures of series and particles on small subjects."""

from __future__ import annotations

from datetime import UTC, datetime

import matplotlib.dates as mdates
import numpy as np
import pandas as pd
import pytest

import hydromodpy as hmp
from hydromodpy.display import static
from hydromodpy.display.special import (
    ensemble_band,
    particle_tracks,
    recession,
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
from tests.unit.display._stored_run import ZONE_AREA

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


def with_particles(monkeypatch, run, years, porosity=0.1):
    """Give the run one two-step pathline per travel time, as ``read_particle_tracks`` does."""
    tracks = [
        np.array([[100.0 * i, 0.0, 0.0, 0.0], [100.0 * i + 50.0, 10.0, 0.0, t * 365.25]])
        for i, t in enumerate(years)
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


def test_the_particle_tracks_draw_one_line_per_particle_that_moved(stored_run, monkeypatch):
    ax = drawn(
        particle_tracks, with_particles(monkeypatch, stored_run, [0.0, *np.arange(1.0, 11.0)])
    )
    assert len(ax.collections[0].get_segments()) == 10
    assert len(ax.collections) == 2  # the lines and the catchment outline, the run has no outlet


@pytest.mark.parametrize(
    "module", [recession, residence_time_distribution, particle_tracks, ensemble_band]
)
def test_a_subject_without_the_data_is_not_applicable(stored_run, module):
    subject = Group([stored_run]) if module is ensemble_band else stored_run
    with pytest.raises(FigureNotApplicable):
        drawn(module, subject)
