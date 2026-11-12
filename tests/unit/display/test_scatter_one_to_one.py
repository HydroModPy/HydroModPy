"""One-to-one scatter of simulated against observed discharge (m3/s), with the score the run recorded.

The figure prints the NSE, RMSE, window and sample count read from the run,
never a score of its own. Pairs outside the scoring window are drawn apart.
"""

from __future__ import annotations

import datetime
from types import SimpleNamespace

import numpy as np
import pandas as pd

from hydromodpy.display.figures.scatter_one_to_one import ScatterOneToOne
from hydromodpy.results.record.manifest import MetricRow
from hydromodpy.results.run.sealed import metrics_of
from hydromodpy.results.storage.run_store import RunStore

# Each stamp closes the month before it, as a run stamps its periods.
STAMPS = pd.date_range("2000-02-01", periods=36, freq="MS")
GAUGE = "NANCON"


class ScoredRun:
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
                window_start=datetime.date(2001, 1, 1),
                window_end=datetime.date(2002, 12, 31),
                n_samples=24,
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
        return ["catchment"] if variable == "discharge" else []

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


class FactsStore(RunStore):
    """A store reduced to its facts, as the display step opens a run before the seal."""

    def __init__(self, metrics: list[MetricRow]) -> None:
        self._facts = SimpleNamespace(metrics=metrics)


def text_of(ax) -> str:
    return "\n".join(text.get_text() for text in ax.texts)


def test_prints_the_score_of_the_run(mpl) -> None:
    fig, ax = mpl.subplots()

    ScatterOneToOne().render(ScoredRun(), ax)

    text = text_of(ax)
    assert "NSE 0.913" in text
    assert "RMSE 0.12" in text
    assert "scored 2001-01-01 to 2002-12-31, n 24" in text


def test_draws_unscored_pairs_apart(mpl) -> None:
    fig, ax = mpl.subplots()

    ScatterOneToOne().render(ScoredRun(), ax)

    scored, unscored = (
        len(collection.get_offsets())
        for collection in sorted(
            ax.collections, key=lambda c: str(c.get_label()) != "not scored", reverse=True
        )
    )
    assert scored == 24
    assert unscored > 0


def test_unscored_run_prints_no_number(mpl) -> None:
    fig, ax = mpl.subplots()

    ScatterOneToOne().render(ScoredRun(scored=False), ax)

    text = text_of(ax)
    assert "holds no score" in text
    assert "NSE" not in text


def test_run_on_its_store_reads_the_facts_before_the_seal() -> None:
    run = SimpleNamespace(
        _catalog_handle=FactsStore([MetricRow(station=GAUGE, metric="nse", value=0.5)])
    )

    frame = metrics_of(run)

    assert frame[["station", "metric", "value"]].to_numpy().tolist() == [[GAUGE, "nse", 0.5]]
