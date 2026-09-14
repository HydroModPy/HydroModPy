"""Tests for the GR4J / lumped lightweight RAM extraction.

Lumped models never write Parquet during a calibration trial. The Gr4jAdapter
must read its hot series from a per-trial :class:`LumpedRamCache` attached to
the execution registry when ``store=None``.
"""

from __future__ import annotations

from types import SimpleNamespace

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


def _make_ctx(execution) -> SimpleNamespace:
    return SimpleNamespace(state=SimpleNamespace(execution=execution), run=None)


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
    execution = SimpleNamespace()
    series = pd.Series([4.0, 5.0])
    stash_series(execution, "outlet", "discharge", series)

    loaded = load_series(execution, "outlet", "discharge")
    assert loaded is not None
    assert list(loaded.values) == [4.0, 5.0]


def test_gr4j_adapter_reads_ram_cache_when_store_is_none() -> None:
    """``store=None`` must trigger the RAM-only lightweight path."""
    execution = SimpleNamespace()
    series = pd.Series([0.1, 0.2, 0.3, 0.4], name="discharge")
    stash_series(execution, "outlet", "discharge", series)

    ctx = _make_ctx(execution)
    adapter = Gr4jAdapter()

    served = adapter.extract_observables(ctx, None, [_discharge_request()])
    result = served["q"]
    assert isinstance(result.values, np.ndarray)
    np.testing.assert_array_equal(result.values, np.array([0.1, 0.2, 0.3, 0.4]))


def test_gr4j_adapter_raises_when_ram_cache_missing_series() -> None:
    """A missing RAM entry must raise a clear ``KeyError``."""
    execution = SimpleNamespace()
    ctx = _make_ctx(execution)
    adapter = Gr4jAdapter()

    with pytest.raises(KeyError, match="No GR4J RAM-cached series"):
        adapter.extract_observables(ctx, None, [_discharge_request()])
