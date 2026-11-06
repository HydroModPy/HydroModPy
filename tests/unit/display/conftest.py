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
