"""Active-network masks of a run: which cells carry water, by mode and flow regime."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from hydromodpy.results.derive import views


def fake_run(flow_regime: str) -> SimpleNamespace:
    """A run of two timesteps over three cells, reduced to what the active mask reads."""
    stack = np.array([[1.0, 0.0, 1.0], [0.0, 0.0, 1.0]])
    zarr_store = SimpleNamespace(
        root={"mesh": {"topography": np.ones(stack.shape[1])}},
        read_field=lambda _variable, timestep, layer=None: stack[timestep],
        close=lambda: None,
    )
    return SimpleNamespace(
        flow_regime=flow_regime,
        n_timesteps=stack.shape[0],
        _sim_id="fake",
        _catalog=SimpleNamespace(open_zarr=lambda _sim_id: zarr_store),
        _load_row=lambda: {"flow_regime": flow_regime},
    )


def test_default_mode_persistent_cells() -> None:
    mask = views.cell_field_active_mask(fake_run("transient"))

    np.testing.assert_array_equal(mask, np.asarray([1.0, 0.0, 1.0]))


def test_perennial_alias() -> None:
    sim = fake_run("transient")

    assert views.resolve_cell_field_active_mode(sim, "perennial") == "always_active"
