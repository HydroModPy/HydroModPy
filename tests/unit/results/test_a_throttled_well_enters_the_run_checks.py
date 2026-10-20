"""A well that AUTO_FLOW_REDUCE cut is a fact of the run, not only a log line.

The solver adapter hands the pumped share of the wells to the run as a metric.
The post-run step turns it into a validity of the checks: a non-fatal one, that
fails below the share a cut is reported at, and passes above it. The seal then
carries it in ``manifest.json`` and the README.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from hydromodpy.physics.flow.sinks_sources.wells import (
    WELLS_PUMPED_CHECK,
    WELLS_PUMPED_METRIC,
    pumped_percent,
)
from hydromodpy.simulation.extraction.post_run import record_run_execution_metrics
from tests._helpers.run_stores import open_run_store

pytestmark = pytest.mark.unit


def _record(tmp_path: Path, metrics: dict[str, float]):
    store = open_run_store(tmp_path / "proj", "demo")
    ctx = SimpleNamespace(run=SimpleNamespace(is_solver_backed=True, id="flow_main"))
    result = SimpleNamespace(metrics=metrics)
    record_run_execution_metrics(ctx=ctx, sim_id=store.sim_id, store=store, result=result)
    return store


def test_the_pumped_share_is_applied_over_requested() -> None:
    requested = {(0, 4): -756000.0, (1, 2): -100.0}
    applied = {(0, 4): -131858.0, (1, 2): -100.0}

    assert pumped_percent(requested, applied) == pytest.approx(
        100.0 * (131858.0 + 100.0) / (756000.0 + 100.0)
    )


def test_a_run_without_a_requested_volume_has_no_pumped_share() -> None:
    assert pumped_percent({}, {}) is None
    assert pumped_percent({(0, 1): 0.0}, {(0, 1): 0.0}) is None


def test_a_cut_well_fails_a_non_fatal_validity(tmp_path: Path) -> None:
    store = _record(tmp_path, {WELLS_PUMPED_METRIC: 17.4})
    try:
        (validity,) = store.facts.validities
        assert validity.name == WELLS_PUMPED_CHECK
        assert validity.passed is False
        assert validity.fatal is False
        assert validity.value == pytest.approx(17.4)
        assert "17 %" in validity.message
        assert store.facts.metrics[0].metric == WELLS_PUMPED_METRIC
    finally:
        store.close()


def test_a_fully_pumped_well_passes(tmp_path: Path) -> None:
    store = _record(tmp_path, {WELLS_PUMPED_METRIC: 99.6})
    try:
        (validity,) = store.facts.validities
        assert validity.passed is True
    finally:
        store.close()


def test_a_run_without_wells_carries_no_such_validity(tmp_path: Path) -> None:
    store = _record(tmp_path, {})
    try:
        assert store.facts.validities == []
    finally:
        store.close()
