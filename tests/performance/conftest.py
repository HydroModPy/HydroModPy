"""Pytest configuration for the performance baseline tier.

Each module under ``tests/performance/`` sets ``pytestmark =
pytest.mark.performance`` so the suite is selectable via
``pytest -m performance``. Benchmarks are self-contained: they avoid
any dependency on hydromodpy runtime so the baseline survives across
the v2 refactor phases (P1 to P15).
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
        item.add_marker(skip)
