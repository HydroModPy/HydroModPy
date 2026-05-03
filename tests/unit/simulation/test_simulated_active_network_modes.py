from __future__ import annotations

import numpy as np

from hydromodpy.results import views


class _FakeZarr:
    def __init__(self, n_cells: int) -> None:
        self.root = {"mesh": {"surface_top": np.ones(n_cells, dtype="float64")}}

    def close(self) -> None:
        return None


class _FakeCatalog:
    def __init__(self, n_cells: int) -> None:
        self._n_cells = n_cells

    def open_zarr(self, _sim_id: str) -> _FakeZarr:
        return _FakeZarr(self._n_cells)


class _FakeRun:
    def __init__(self, *, flow_regime: str, stack: np.ndarray) -> None:
        self.flow_regime = flow_regime
        self.n_timesteps = stack.shape[0]
        self._stack = stack
        self._sim_id = "fake"
        self._catalog = _FakeCatalog(stack.shape[1])

    def _load_row(self) -> dict[str, str]:
        return {"flow_regime": self.flow_regime}

    def field(self, _variable: str, *, timestep: int) -> np.ndarray:
        return self._stack[timestep]


def _fake_run(flow_regime: str) -> _FakeRun:
    stack = np.asarray(
        [
            [1.0, 0.0, 1.0],
            [0.0, 0.0, 1.0],
        ],
        dtype="float64",
    )
    return _FakeRun(flow_regime=flow_regime, stack=stack)


def test_active_network_default_mode_uses_last_step_for_steady_runs() -> None:
    mask = views.simulated_active_network_mask(_fake_run("steady"))

    np.testing.assert_array_equal(mask, np.asarray([0.0, 0.0, 1.0]))


def test_active_network_default_mode_uses_persistent_cells_for_transient_runs() -> None:
    mask = views.simulated_active_network_mask(_fake_run("transient"))

    np.testing.assert_array_equal(mask, np.asarray([1.0, 0.0, 1.0]))


def test_active_network_perennial_alias_resolves_to_always_active() -> None:
    sim = _fake_run("transient")

    assert views.resolve_simulated_active_network_mode(sim, "perennial") == "always_active"
