"""``nse_log`` has one rule for a negative value: clip it to zero and count it.

A discharge reconstructed below a dam can hold a few negative values. The
calibration clipped them and counted them, the run score returned ``None``, the
core kernel raised and the Brutsaert case returned NaN (N10 of the audit of
2026-10-20, decision m12). Now the run and the calibration clip alike, and the
run writes ``n_clipped`` on the row of ``nse_log``: 0 when nothing was clipped,
``None`` on a metric that never clips.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from hydromodpy.calibration.criteria.series import SeriesCriterion
from hydromodpy.core import metrics as core
from hydromodpy.results.catalog import Catalog
from hydromodpy.results.catalog.indexer import rebuild_index
from hydromodpy.results.fit_metrics import score_timeseries
from hydromodpy.results.metric_rule import DateWindow, MetricRule, score
from hydromodpy.results.storage.sealing import seal_completed
from tests._helpers.metric_rows import headline_row, headline_score
from tests._helpers.run_stores import open_run_store
from validation_cases.calibration.recession_hillslope_aquifer import experiment as case

WINDOW = DateWindow(start=date(2001, 1, 1), end=date(2001, 1, 10))
RULE = MetricRule(station="S", window=WINDOW)
DAYS = pd.date_range("2001-01-01", periods=10, freq="D")
OBSERVED = pd.Series([4.0, 3.5, 3.0, 2.6, 2.2, 1.9, 1.6, 1.4, 1.2, 1.0], index=DAYS)
CLEAN = OBSERVED * np.array([1.1, 0.9, 1.05, 0.95, 1.2, 0.85, 1.1, 0.9, 1.3, 0.8])
BELOW_ZERO = CLEAN.copy()
BELOW_ZERO.iloc[3] = -0.4
BELOW_ZERO.iloc[7] = -0.1


def test_the_core_kernel_clips_instead_of_raising() -> None:
    expected = core.log_nse(np.clip(BELOW_ZERO.to_numpy(), 0.0, None), OBSERVED.to_numpy())

    assert core.log_nse(BELOW_ZERO.to_numpy(), OBSERVED.to_numpy()) == pytest.approx(expected)


def test_the_run_scores_a_negative_value_and_counts_the_clipping() -> None:
    result = score(BELOW_ZERO, OBSERVED, RULE, "nse_log")

    assert result.value is not None
    assert np.isfinite(result.value)
    assert result.n_clipped == 2


def test_a_clipping_on_the_observed_side_counts_too() -> None:
    observed = OBSERVED.copy()
    observed.iloc[0] = -2.0

    assert score(CLEAN, observed, RULE, "nse_log").n_clipped == 1


def test_a_clean_series_writes_zero_on_nse_log_and_none_elsewhere() -> None:
    assert score(CLEAN, OBSERVED, RULE, "nse_log").n_clipped == 0
    assert score(BELOW_ZERO, OBSERVED, RULE, "nse").n_clipped is None
    assert score(BELOW_ZERO, OBSERVED, RULE, "rmse").n_clipped is None


def test_the_run_score_is_the_calibration_score_on_the_same_pairs() -> None:
    from_run = score(BELOW_ZERO, OBSERVED, RULE, "nse_log")
    from_calibration = SeriesCriterion("nse_log", core.log_nse).score(
        BELOW_ZERO.to_numpy(), OBSERVED.to_numpy()
    )

    assert from_run.value == pytest.approx(from_calibration.diagnostics["score"], abs=1e-15)
    assert from_run.n_clipped == int(from_calibration.diagnostics["n_clipped"])


def test_the_row_of_a_run_carries_n_clipped() -> None:
    def rows(values: pd.Series) -> list[dict]:
        sim = [
            {
                "station_id": "_c",
                "variable": "discharge",
                "source": "simulated",
                "time": t + pd.Timedelta(1, unit="D"),
                "value": v,
            }
            for t, v in zip(DAYS.tz_localize("UTC"), values, strict=True)
        ]
        obs = [
            {
                "station_id": "S",
                "variable": "discharge",
                "source": "observed",
                "time": t,
                "value": v,
            }
            for t, v in zip(DAYS.tz_localize("UTC"), OBSERVED, strict=True)
        ]
        return sim + obs

    scores = score_timeseries(pd.DataFrame(rows(BELOW_ZERO)), rule=RULE)

    by_metric = {row.metric: row for row in scores.rows}
    assert by_metric["nse_log"].n_clipped == 2
    assert by_metric["nse_log"].value is not None
    assert by_metric["nse"].n_clipped is None


def test_the_brutsaert_case_follows_the_same_rule() -> None:
    bundle = case._compute_metrics(OBSERVED.to_numpy(), BELOW_ZERO.to_numpy())

    assert bundle["NSElog"] == pytest.approx(
        core.log_nse(BELOW_ZERO.to_numpy(), OBSERVED.to_numpy())
    )
    assert np.isfinite(bundle["NSElog"])


def test_the_store_the_seal_and_the_index_keep_n_clipped(tmp_path) -> None:
    root = tmp_path / "p"
    store = open_run_store(root, "a", create_zarr=False)
    store.write_metric(
        store.sim_id,
        headline_row("nse_log", 0.5, station="S", window=WINDOW, n_clipped=2),
    )
    store.facts.score = headline_score(0.5, station="S", window=WINDOW)
    seal_completed(store)
    rebuild_index(root)

    with Catalog(root) as cat:
        frame = cat.sql("SELECT metric_name, n_clipped FROM metrics")

    assert frame.set_index("metric_name")["n_clipped"].to_dict() == {"nse_log": 2}
