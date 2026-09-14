"""Pytest configuration for the performance baseline tier.

Each module under ``tests/performance/`` sets ``pytestmark =
pytest.mark.performance`` so the suite is selectable via
``pytest -m performance``. Benchmarks exercise the thin HydroModPy storage
wrappers (Catalog over DuckDB, the Zarr field backend, the Parquet
timeseries backend) so a regression in those wrappers is caught by the
ratio-based drift gate in ``perf.yml``.
"""

from __future__ import annotations

from importlib.util import find_spec

import pytest


def pytest_configure(config: pytest.Config) -> None:
    """Register benchmark marks even when pytest-benchmark is not installed."""
    config.addinivalue_line("markers", "benchmark(*args, **kwargs): performance benchmark")


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Skip performance tests when the benchmark plugin extra is absent."""
    if find_spec("pytest_benchmark") is not None:
        return
    skip = pytest.mark.skip(reason="pytest-benchmark is not installed")
    for item in items:
        if "performance" in item.keywords:
            item.add_marker(skip)
