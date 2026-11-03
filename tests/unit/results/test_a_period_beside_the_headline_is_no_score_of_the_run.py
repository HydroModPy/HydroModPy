"""A run keeps every period it was scored on, and every ranking reads the headline one.

A validation period sits beside ``[metrics] window`` in the ``metrics`` table. The
long view of a run lists both. The wide view, the selectors, ``find``, a set of
runs and the dataset loader read the period named ``metrics`` alone, so a score
of another period never makes a run best.
"""

from __future__ import annotations

from datetime import date

import pytest

from hydromodpy.results.catalog import Catalog
from hydromodpy.results.catalog.indexer import rebuild_index
from hydromodpy.results.metric_rule import HEADLINE_WINDOW, DateWindow
from hydromodpy.results.storage.sealing import seal_completed
from tests._helpers.metric_rows import headline_row, headline_score
from tests._helpers.run_stores import open_run_store

VALIDATION = DateWindow(start=date(2010, 1, 1), end=date(2012, 12, 31))
SCORES = {"low": (0.6, 0.99), "high": (0.7, 0.1)}
"""Headline score, then the score of a validation period, of each run."""


@pytest.fixture
def cat(tmp_path):
    root = tmp_path / "p"
    ids = {}
    for name, (headline, validation) in SCORES.items():
        store = open_run_store(root, name, create_zarr=False)
        store.facts.put_metric(headline_row("nse", headline))
        store.facts.put_metric(
            headline_row(
                "nse",
                validation,
                window=VALIDATION,
                window_name="validation",
                window_role="validation",
            )
        )
        store.facts.score = headline_score(headline)
        seal_completed(store)
        ids[name] = store.sim_id
    rebuild_index(root)
    with Catalog(root) as catalog:
        yield catalog, ids


def test_the_long_view_of_a_run_lists_every_period(cat) -> None:
    catalog, _ids = cat
    frame = catalog["low"].metrics
    assert dict(zip(frame["window_name"], frame["value"], strict=True)) == {
        HEADLINE_WINDOW: 0.6,
        "validation": 0.99,
    }
    assert set(frame["window_role"]) == {"evaluation", "validation"}


def test_the_selectors_and_the_filter_rank_on_the_headline_period(cat) -> None:
    catalog, ids = cat
    assert catalog.resolve("@best:nse") == ids["high"]
    assert catalog.resolve("@worst:nse") == ids["low"]
    assert catalog.find(nse_gt=0.65).sim_ids == [ids["high"]]


def test_the_wide_view_the_set_and_the_loader_read_the_headline_period(cat) -> None:
    catalog, ids = cat
    wide = catalog.sql("SELECT sim_id, nse FROM v_metrics_wide")
    assert dict(zip(wide["sim_id"].astype(str), wide["nse"], strict=True)) == {
        ids["low"]: 0.6,
        ids["high"]: 0.7,
    }
    frame = catalog.find().metrics.set_index("sim_id")
    assert frame.loc[ids["high"], "nse"] == 0.7
    dataset = catalog.load_dataset()
    assert dict(zip(dataset["sim_id"].values, dataset["metric_nse"].values, strict=True)) == {
        ids["low"]: 0.6,
        ids["high"]: 0.7,
    }
