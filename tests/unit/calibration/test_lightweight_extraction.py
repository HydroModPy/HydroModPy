"""Tests for the GR4J / lumped lightweight RAM extraction.

Lumped models never write Parquet during a calibration trial. The Gr4jAdapter
must read its hot series from a per-trial :class:`LumpedRamCache`, which is what
that run produced and reaches the adapter on its ``RunContext`` when
``store=None``.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from hydromodpy.calibration.config import CalibrationConfig
from hydromodpy.calibration.lumped import (
    Gr4jAdapter,
    LumpedRamCache,
    load_series,
    stash_series,
)
from hydromodpy.core.contracts.observables import ObservableRequest
from hydromodpy.core.state.run_state import WorkflowContext
from hydromodpy.simulation.planning.plan import ProcessRun, RunContext, SimulationPlan

GR4J_RUN = ProcessRun(
    id="flow_main::gr4j",
    process_id="flow_main",
    process_type="flow",
    solver="gr4j",
)
GR4J_PLAN = SimulationPlan(name="gr4j", description="gr4j", runs=(GR4J_RUN,))


def _trial_context() -> WorkflowContext:
    return WorkflowContext(cfg=None, config_path=Path("run_gr4j.toml"), raw_toml={})


def _make_ctx(trial: WorkflowContext) -> RunContext:
    """The adapter's context, built through the one production path."""
    return RunContext.of(trial, plan=GR4J_PLAN, run=GR4J_RUN)


def _discharge_request() -> ObservableRequest:
    """GR4J is lumped, so discharge sits on the domain support."""
    return ObservableRequest(id="q", name="discharge", support="domain")


def test_calibration_config_has_lightweight_extraction_default_true() -> None:
    cfg = CalibrationConfig()
    assert cfg.lightweight_extraction is True


def test_ram_cache_round_trip() -> None:
    cache = LumpedRamCache()
    cache.put("outlet", "discharge", pd.Series([1.0, 2.0, 3.0]))
    out = cache.get("outlet", "discharge")
    assert out is not None
    assert list(out.values) == [1.0, 2.0, 3.0]
    assert ("outlet", "discharge") in cache
    assert len(cache) == 1


def test_stash_and_load_series_create_cache_lazily() -> None:
    trial = _trial_context()
    series = pd.Series([4.0, 5.0])
    stash_series(trial.execution, "outlet", "discharge", series)

    loaded = load_series(trial.execution.lumped_ram_cache, "outlet", "discharge")
    assert loaded is not None
    assert list(loaded.values) == [4.0, 5.0]


def test_gr4j_adapter_reads_ram_cache_when_store_is_none() -> None:
    """``store=None`` must trigger the RAM-only lightweight path."""
    trial = _trial_context()
    series = pd.Series([0.1, 0.2, 0.3, 0.4], name="discharge")
    stash_series(trial.execution, "outlet", "discharge", series)

    ctx = _make_ctx(trial)
    adapter = Gr4jAdapter()

    served = adapter.extract_observables(ctx, None, [_discharge_request()])
    result = served["q"]
    assert isinstance(result.values, np.ndarray)
    np.testing.assert_array_equal(result.values, np.array([0.1, 0.2, 0.3, 0.4]))


def test_gr4j_adapter_raises_when_ram_cache_missing_series() -> None:
    """A missing RAM entry must raise a clear ``KeyError``."""
    ctx = _make_ctx(_trial_context())
    adapter = Gr4jAdapter()

    with pytest.raises(KeyError, match="No GR4J RAM-cached series"):
        adapter.extract_observables(ctx, None, [_discharge_request()])


def test_the_cache_a_trial_stashed_is_the_one_the_adapter_receives() -> None:
    """The context carries the run's product; the registry is not read twice.

    ``RunContext.of`` snapshots the cache, so a trial that stashes AFTER the
    context was built serves nothing. Pinned because the two orders are
    indistinguishable in the passing case.
    """
    trial = _trial_context()
    ctx = _make_ctx(trial)
    stash_series(trial.execution, "outlet", "discharge", pd.Series([1.0]))

    assert ctx.lumped_cache is None
    with pytest.raises(KeyError, match="No GR4J RAM-cached series"):
        Gr4jAdapter().extract_observables(ctx, None, [_discharge_request()])
