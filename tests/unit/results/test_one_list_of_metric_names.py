"""One list of metric names: what a producer writes has a direction, and the reverse.

Four lists of the same thing had drifted: the wide view pivoted twenty names, the
run kernels computed eleven, the direction table held twenty-five and the
calibration criteria their own ten. ``r2``, ``mse`` and ``kge_delta`` had a
direction and no producer, and the wide view carried columns nothing filled.
"""

from __future__ import annotations

from datetime import date

import pytest

from hydromodpy.analysis.comparison.run_comparison import CLOSURE_METRIC_NAMES
from hydromodpy.calibration.criteria.series import METRICS as CALIBRATION_METRICS
from hydromodpy.results.catalog import Catalog
from hydromodpy.results.catalog.constants import METRIC_SENSE, RETIRED_METRIC_NAMES
from hydromodpy.results.catalog.indexer import rebuild_index
from hydromodpy.results.manifest import MetricRow
from hydromodpy.results.metric_rule import METRIC_NAMES, METRIC_RULE_VERSION
from hydromodpy.results.storage.sealing import seal_completed
from tests._helpers.run_stores import open_run_store

PRODUCERS = {
    "the run kernels": set(METRIC_NAMES),
    "the calibration criteria": set(CALIBRATION_METRICS),
    "the closure of a comparison": set(CLOSURE_METRIC_NAMES),
}


def test_every_name_a_producer_writes_has_a_direction() -> None:
    for producer, names in PRODUCERS.items():
        assert names <= set(METRIC_SENSE), (
            f"{producer} write(s) without a direction: {sorted(names - set(METRIC_SENSE))}"
        )


def test_every_direction_has_a_producer() -> None:
    produced = set().union(*PRODUCERS.values())
    assert set(METRIC_SENSE) <= produced, (
        f"a direction nothing produces: {sorted(set(METRIC_SENSE) - produced)}"
    )


def test_a_retired_name_is_no_known_name() -> None:
    assert not set(RETIRED_METRIC_NAMES) & set(METRIC_SENSE)


@pytest.fixture
def index(tmp_path):
    project = tmp_path / "p"
    store = open_run_store(project, "a", create_zarr=False)
    store.facts.put_metric(
        MetricRow(
            station="J0014010",
            variable="discharge",
            metric="nse",
            value=0.5,
            nse_window_start=date(2016, 1, 1),
            nse_window_end=date(2020, 12, 31),
            nse_n=10,
            metric_rule_version=METRIC_RULE_VERSION,
        )
    )
    seal_completed(store)
    rebuild_index(project)
    with Catalog(project) as cat:
        yield cat


def test_the_wide_view_pivots_the_names_the_kernels_compute(index) -> None:
    columns = index.sql("SELECT * FROM v_metrics_wide").columns
    pivoted = [c for c in columns if c not in {"sim_id", "station_id", "variable"}]
    assert pivoted == list(METRIC_NAMES)
