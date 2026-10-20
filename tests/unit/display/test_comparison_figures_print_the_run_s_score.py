"""The comparison figures print the score the run recorded, never one of their own.

``scatter_one_to_one`` scored the pairs it drew, on every shared timestamp,
spin-up included; ``hydrograph_log_nse`` printed whatever window and NSElog
were typed beside it. Both now read the scores the run recorded on
``[metrics] window``, with that window and its sample count, from the seal or,
before it, from the facts of the run's store.
"""

from __future__ import annotations

import datetime
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from hydromodpy.display.figures.hydrograph_log_nse import HydrographLogNseFigure
from hydromodpy.display.figures.scatter_one_to_one import ScatterOneToOne
from hydromodpy.results.manifest import MetricRow
from hydromodpy.results.storage.run_store import RunStore

# Each stamp closes the month before it, as a run stamps its periods.
STAMPS = pd.date_range("2000-02-01", periods=36, freq="MS")
GAUGE = "NANCON"


@pytest.fixture
def mpl():
    pytest.importorskip("matplotlib")
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    yield plt
    plt.close("all")


class _Run:
    """Three monthly years and their gauge, scored on 2001-2002 as the derive step does."""

    sim_id = "sim-nancon"
    name = "nancon"

    def __init__(self, *, scored: bool = True) -> None:
        months = np.arange(STAMPS.size, dtype=float)
        self._sim = pd.Series(1.0 + 0.5 * np.cos(2.0 * np.pi * months / 12.0), index=STAMPS)
        self._obs = self._sim * 1.1 + 0.05
        rows = [
            MetricRow(
                station=GAUGE,
                variable="discharge",
                metric=metric,
                value=value,
                nse_window_start=datetime.date(2001, 1, 1),
                nse_window_end=datetime.date(2002, 12, 31),
                nse_n=24,
                metric_rule_version="1",
            ).model_dump()
            for metric, value in (("nse", 0.913), ("nse_log", 0.876), ("rmse", 0.12))
        ]
        columns = list(MetricRow.model_fields)
        self.metrics = pd.DataFrame(rows if scored else [], columns=columns)

    def has_table(self, table: str) -> bool:
        return table == "timeseries"

    def has_field(self, variable: str, **_) -> bool:
        return False

    def stations(self, variable: str) -> list[str]:
        return ["_catchment"] if variable == "discharge" else []

    def timeseries(self, variable: str, *, station: str | None = None, **_) -> pd.Series:
        if variable != "discharge":
            raise KeyError(variable)
        return self._sim.copy()

    def observed(self, variable: str, station: str | None = None, **_) -> pd.DataFrame:
        days = pd.date_range("2000-01-01", STAMPS[-1], freq="D")
        daily = self._obs.reindex(days, method="bfill")
        return pd.DataFrame(
            {
                "station_id": [GAUGE] * days.size,
                "datetime": days,
                "variable": [variable] * days.size,
                "value": daily.to_numpy(),
            }
        )


def _text(ax) -> str:
    return "\n".join(text.get_text() for text in ax.texts)


def test_the_scatter_prints_the_score_of_the_run(mpl) -> None:
    fig, ax = mpl.subplots()

    ScatterOneToOne().render(_Run(), ax)

    text = _text(ax)
    assert "NSE 0.913" in text
    assert "RMSE 0.12" in text
    assert "scored 2001-01-01 to 2002-12-31, n 24" in text
    mpl.close(fig)


def test_the_scatter_draws_the_pairs_the_score_left_out_apart(mpl) -> None:
    fig, ax = mpl.subplots()

    ScatterOneToOne().render(_Run(), ax)

    scored, unscored = (
        len(collection.get_offsets())
        for collection in sorted(
            ax.collections, key=lambda c: str(c.get_label()) != "not scored", reverse=True
        )
    )
    assert scored == 24
    assert unscored > 0
    mpl.close(fig)


def test_the_scatter_of_an_unscored_run_prints_no_number(mpl) -> None:
    fig, ax = mpl.subplots()

    ScatterOneToOne().render(_Run(scored=False), ax)

    text = _text(ax)
    assert "holds no score" in text
    assert "NSE" not in text
    mpl.close(fig)


def test_the_log_hydrograph_shades_and_prints_what_the_run_recorded(mpl) -> None:
    fig, ax = mpl.subplots()

    HydrographLogNseFigure().render(_Run(), ax)

    text = _text(ax)
    assert "NSElog = 0.876" in text
    assert "scoring window 2001-01-01 to 2002-12-31: 24 of 36 samples scored" in text
    (span,) = [patch for patch in ax.patches if patch.get_label() == "scoring window"]
    assert span is not None
    mpl.close(fig)


class _Store(RunStore):
    """A store reduced to its facts, as the display step opens a run before the seal."""

    def __init__(self, metrics: list[MetricRow]) -> None:
        self._facts = SimpleNamespace(metrics=metrics)


def test_a_run_on_its_store_reads_the_facts_before_the_seal() -> None:
    from hydromodpy.results.run.sealed import metrics_of

    run = SimpleNamespace(
        _catalog_handle=_Store([MetricRow(station=GAUGE, metric="nse", value=0.5)])
    )

    frame = metrics_of(run)

    assert frame[["station", "metric", "value"]].to_numpy().tolist() == [[GAUGE, "nse", 0.5]]
