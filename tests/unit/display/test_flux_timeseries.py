"""The water-balance figure draws the boundary fluxes and leaves the storage out by default."""

from __future__ import annotations

from types import SimpleNamespace

import matplotlib.pyplot as plt
import pandas as pd
import pytest

from hydromodpy.display.figures.flux_timeseries import FluxTimeseries

_COMPONENTS = ("recharge", "drain", "storage", "storage_ss", "storage_sy", "river")


def _run() -> SimpleNamespace:
    """A run without dates whose budget holds every component above, two steps."""
    rows = [
        {"component": c, "timestep": t, "flux_in": 1.0 + t, "flux_out": 0.5}
        for c in _COMPONENTS
        for t in range(2)
    ]
    return SimpleNamespace(sim_id="sim-flux", budget=lambda: pd.DataFrame(rows))


@pytest.mark.parametrize(
    ("include_storage", "drawn"),
    [
        (False, {"recharge", "drain", "river"}),
        (True, {"recharge", "drain", "river", "storage", "storage ss", "storage sy"}),
    ],
    ids=["storage_left_out", "storage_drawn"],
)
def test_the_storage_family_is_drawn_only_on_request(include_storage, drawn) -> None:
    fig, ax = plt.subplots()
    try:
        FluxTimeseries().render(_run(), ax, include_storage=include_storage)
        labels = {
            line.get_label() for line in ax.get_lines() if not line.get_label().startswith("_")
        }
    finally:
        plt.close(fig)

    assert labels == drawn
