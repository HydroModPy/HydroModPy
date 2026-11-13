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


@pytest.fixture(scope="session")
def stored_run(tmp_path_factory):
    """One small sealed run read through the public API, shared by the figure tests."""
    from tests.unit.display._stored_run import open_stored_run

    return open_stored_run(tmp_path_factory.mktemp("stored_run") / "proj")
