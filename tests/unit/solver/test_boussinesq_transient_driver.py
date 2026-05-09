from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from hydromodpy.solver.boussinesq.drivers.transient import (
    _resolve_period_lengths_seconds,
)


def test_resolve_period_lengths_seconds_uses_positive_grid_lengths() -> None:
    grid = SimpleNamespace(period_lengths_seconds=(10.0, 20.0), boundaries=())

    assert _resolve_period_lengths_seconds(grid) == (10.0, 20.0)


def test_resolve_period_lengths_seconds_falls_back_to_boundaries_for_zero_lengths() -> None:
    start = datetime(2020, 1, 1)
    grid = SimpleNamespace(
        period_lengths_seconds=(0.0, 0.0),
        boundaries=(start, start + timedelta(days=1), start + timedelta(days=3)),
    )

    assert _resolve_period_lengths_seconds(grid) == (86400.0, 172800.0)


def test_resolve_period_lengths_seconds_rejects_zero_lengths_without_boundaries() -> None:
    grid = SimpleNamespace(period_lengths_seconds=(0.0,), boundaries=())

    with pytest.raises(ValueError, match="non-positive period lengths"):
        _resolve_period_lengths_seconds(grid)
