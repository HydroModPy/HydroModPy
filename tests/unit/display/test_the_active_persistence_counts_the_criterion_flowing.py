"""The persistence of the active-network map counts the cells the criterion calls flowing.

The run is the monthly V-valley of :mod:`tests.unit.results._transient_network_run`,
27 monthly steps: the whole axis flows in the 13 winter months, the outlet
alone in the 14 others at two litres per second. With the default visible flow
of 1 L/s the outlet flows at every step and the two upper axis cells at 13 of
27. A field cut on ``accumulation_flux`` would read another network, so the
map draws the criterion's count unless a caller names a field, and a run the
criterion graph cannot be rebuilt on falls back to the field and says why.
"""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.display.figures.simulated_active_network import (
    SimulatedActiveNetworkMap,
    flowing_persistence,
)
from hydromodpy.results.derive import views
from tests.unit.display._network_comparison_run import NX, NY, legend_note
from tests.unit.results._transient_network_run import (
    HEAD,
    HILLSLOPE,
    MIDDLE,
    N_STEPS,
    OUTLET,
    transient_run,
)

WINTER_STEPS = 13
"""Winter months between January 2001 and March 2003."""


@pytest.fixture
def mpl():
    pytest.importorskip("matplotlib")
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    yield plt
    plt.close("all")


def _sealed(visible_flow: str) -> dict:
    """A snapshot whose one network output scored two bounds at ``visible_flow``."""
    return {
        "calibration": {
            "outputs": {
                "streams": {
                    "support": "network",
                    "observed_network": "data.hydrography",
                    "tau_specific_ratio": 1.0e-4,
                    "extent": {"visible_flow": visible_flow},
                }
            }
        }
    }


def _drawn_share(ax) -> np.ndarray:
    field = next(item for item in ax.collections if item.get_array() is not None)
    return np.asarray(field.get_array(), dtype="float64")


def test_the_share_is_the_criterion_count_over_the_timesteps() -> None:
    flowing, reason = flowing_persistence(transient_run())

    assert reason is None
    assert flowing.share[OUTLET] == pytest.approx(1.0)
    assert flowing.share[MIDDLE] == pytest.approx(WINTER_STEPS / N_STEPS)
    assert flowing.share[HEAD] == pytest.approx(WINTER_STEPS / N_STEPS)
    assert flowing.share[HILLSLOPE] == 0.0


def test_the_map_draws_the_criterion_share_and_names_its_definition(mpl) -> None:
    fig, ax = mpl.subplots()
    SimulatedActiveNetworkMap().render(transient_run(), ax, mode="persistence")

    drawn = _drawn_share(ax)
    assert drawn[OUTLET] == pytest.approx(1.0)
    assert drawn[HEAD] == pytest.approx(WINTER_STEPS / N_STEPS)
    assert np.isnan(drawn[HILLSLOPE]), "a cell that never flows is ground"
    assert "flowing persistence" in ax.get_title()
    note = legend_note(ax)
    assert "a cell counts as seepage above 0.01 % of its recharge" in note
    assert "a cell downstream of seepage flows from 1 L/s" in note
    assert "tau" not in note
    assert "the share of the timesteps each cell flows, drawn uncut" in note
    assert "criterion settings: the defaults, this run sealed no network output" in note
    assert "accumulation_flux" not in note


def test_the_run_sealed_visible_flow_cuts_the_summer_outlet(mpl) -> None:
    """At 5 L/s the two-litre summer outlet no longer flows: 13 of 27 steps."""
    run = transient_run()
    run.config_snapshot = _sealed("5 L/s")
    fig, ax = mpl.subplots()
    SimulatedActiveNetworkMap().render(run, ax, mode="persistence")

    assert _drawn_share(ax)[OUTLET] == pytest.approx(WINTER_STEPS / N_STEPS)
    note = legend_note(ax)
    assert "flows from 5 L/s" in note
    assert "criterion settings: calibration output 'streams'" in note


def test_a_named_field_is_drawn_as_asked(mpl, monkeypatch) -> None:
    fraction = np.full(NX * NY, 0.25)
    monkeypatch.setattr(views, "cell_field_active_mask", lambda *_a, **_k: fraction)
    fig, ax = mpl.subplots()
    SimulatedActiveNetworkMap().render(
        transient_run(), ax, mode="persistence", variable="accumulation_flux"
    )

    assert "active persistence" in ax.get_title()
    note = legend_note(ax)
    assert "active where accumulation_flux > 0" in note
    assert "not the criterion" not in note


def test_a_run_the_criterion_cannot_read_falls_back_and_says_why(mpl, monkeypatch) -> None:
    run = transient_run()
    run.has_field = lambda variable, **_: variable in {"accumulation_flux", "topography"}
    fraction = np.full(NX * NY, 0.25)
    monkeypatch.setattr(views, "cell_field_active_mask", lambda *_a, **_k: fraction)
    fig, ax = mpl.subplots()
    SimulatedActiveNetworkMap().render(run, ax, mode="persistence")

    note = legend_note(ax)
    assert "active where accumulation_flux > 0" in note
    assert "not the criterion's flowing cells: run has no per-cell release_flux" in note
