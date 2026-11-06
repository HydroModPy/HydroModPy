"""Fixtures shared by the display tests."""

from __future__ import annotations

import logging

import pytest

from hydromodpy.core.logging import get_logger


@pytest.fixture
def mpl():
    pytest.importorskip("matplotlib")
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    saved = matplotlib.rcParams.copy()
    yield plt
    plt.close("all")
    matplotlib.rcParams.update(saved)


@pytest.fixture
def hmp_log_records():
    """Capture ``hydromodpy`` records (the parent logger disables propagation)."""
    parent = get_logger("hydromodpy")
    previous_level = parent.level
    parent.setLevel(logging.DEBUG)
    records: list[logging.LogRecord] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    handler = _Capture(level=logging.DEBUG)
    parent.addHandler(handler)
    try:
        yield records
    finally:
        parent.removeHandler(handler)
        parent.setLevel(previous_level)
