"""A ``steady_state`` start runs its steady solve on a variant of the model and leaves the model alone.

The solve used to swap the regime, the time grid, the recharge and the surface
closure of its own flow for the length of the solve, and restore them after.
It now runs on a second solver built over ``steady_variant(model)``, so the model
the main solve reads is never written. A ``ts_vi_obstacle`` run of the ``petsc``
engine took ``AttributeError`` on the closure swap since 2.0.0: its auxiliary
solve runs the ``regularized_partition`` closure.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.model.initial.state import HeadRule, SteadyStart, SteadyStateStrategy
from hydromodpy.model.model import ModelTime
from hydromodpy.model.runtime_config import FlowRuntimeConfig
from hydromodpy.model.sinks_sources.recharge import FlowRechargeConfig
from hydromodpy.solver.boussinesq.boussinesq import Boussinesq
from hydromodpy.solver.boussinesq.drivers import steady as steady_driver
from hydromodpy.solver.boussinesq.state import BoussinesqState
from tests._helpers.model_factory import make_model

from ._row_runs import DAY_S, N_CELLS, OUTLET_M, fixed_forcing, row_mesh

START_M = 30.0
PERIOD_DAYS = (10.0, 20.0, 30.0)
RECHARGE_M_S = 2.0e-3 / DAY_S


def _grid() -> SimpleNamespace:
    return SimpleNamespace(
        period_lengths_seconds=np.asarray(PERIOD_DAYS) * DAY_S,
        nstp_per_period=1,
        window=None,
        boundaries=(),
    )


def _transient_model(**members: object):
    parts: dict[str, object] = {
        "time": ModelTime(grid=_grid(), regime="transient", first_period_steady=False),
        "initial": SteadyStart(),
        "recharge": FlowRechargeConfig(
            values=[RECHARGE_M_S, 2 * RECHARGE_M_S, 0.0], units="m/s", first_clim=1.0e-9
        ),
    }
    return make_model(**{**parts, **members})


def _solver(tmp_path: Path, model, runtime: FlowRuntimeConfig, *, name: str = "init") -> Boussinesq:
    solver = Boussinesq(
        mesh_bundle=None,
        mesh=row_mesh(),
        model=model,
        runtime=runtime,
        model_folder=tmp_path,
        model_name=name,
    )
    head = np.full(N_CELLS, START_M)
    head[0] = OUTLET_M
    solver.state = BoussinesqState.initial(head_m=head, saturated_thickness_m=head.copy())
    return solver


@pytest.fixture
def spy(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    """Replace the nonlinear steady solve by a recorder of what it was given."""
    calls: list[dict] = []

    def record(self: Boussinesq) -> bool:
        calls.append(
            {
                "backend": self.runtime.backend,
                "backend_name": self._runtime_backend_name(),
                "closure": self.runtime.surface_interaction_model,
                "closure_token": self._surface_interaction_model(),
                "regime": self.inputs.time.regime,
                "periods_s": tuple(self.inputs.time.grid.period_lengths_seconds),
                "initial": self.inputs.initial,
                "first_clim": self.inputs.recharge.first_clim,
                "options": self._runtime_options(),
            }
        )
        self.state = BoussinesqState.initial(
            head_m=np.full(N_CELLS, 12.0), saturated_thickness_m=np.full(N_CELLS, 12.0)
        )
        self.runtime_summary["steady_mode"] = "recorded"
        return True

    monkeypatch.setattr(Boussinesq, "_run_steady_runtime", record)
    return calls


PETSC_TS = FlowRuntimeConfig(backend="petsc", surface_interaction_model="ts_vi_obstacle")


def test_the_petsc_ts_vi_obstacle_start_solves_the_regularized_partition_steady_problem(
    tmp_path: Path, spy: list[dict]
) -> None:
    solver = _solver(tmp_path, _transient_model(), PETSC_TS)

    assert solver._run_steady_state_initialization() is True

    (call,) = spy
    assert call["backend"] == call["backend_name"] == "petsc"
    assert call["closure"] == call["closure_token"] == "regularized_partition"
    assert call["regime"] == "steady"
    assert call["periods_s"] == (sum(PERIOD_DAYS) * DAY_S,)
    assert call["initial"] == HeadRule("top")
    assert call["first_clim"] == "mean"
    assert call["options"].regularization_radius == PETSC_TS.partition_release_depth_m


def test_the_main_solve_keeps_its_closure_its_model_and_its_regime(
    tmp_path: Path, spy: list[dict]
) -> None:
    model = _transient_model()
    members = {name: id(getattr(model, name)) for name in model.__dataclass_fields__}
    before = repr(model)
    solver = _solver(tmp_path, model, PETSC_TS)

    solver._run_steady_state_initialization()

    assert solver.inputs is model
    assert repr(model) == before
    assert {name: id(getattr(model, name)) for name in model.__dataclass_fields__} == members
    assert model.recharge.first_clim == 1.0e-9
    assert model.time.regime == "transient"
    assert model.initial == SteadyStart()
    assert solver.runtime.surface_interaction_model == "ts_vi_obstacle"
    assert solver._surface_interaction_model() == "ts_vi_obstacle"
    assert len(model.time.grid.period_lengths_seconds) == len(PERIOD_DAYS)


OTHER_CLOSURES = (
    ("local", "auto"),
    ("scipy_sparse", "auto"),
    ("petsc", "vi_obstacle"),
    ("petsc", "complementarity"),
    ("petsc", "regularized_partition"),
)


@pytest.mark.parametrize(
    ("backend", "closure"), OTHER_CLOSURES, ids=["-".join(c) for c in OTHER_CLOSURES]
)
def test_every_other_start_keeps_the_closure_it_asks_for(
    tmp_path: Path, spy: list[dict], backend: str, closure: str
) -> None:
    runtime = FlowRuntimeConfig(backend=backend, surface_interaction_model=closure)

    _solver(tmp_path, _transient_model(), runtime)._run_steady_state_initialization()

    assert (spy[0]["backend"], spy[0]["closure"]) == (backend, closure)


def test_the_solve_hands_back_its_state_and_its_summary(tmp_path: Path, spy: list[dict]) -> None:
    solver = _solver(tmp_path, _transient_model(), FlowRuntimeConfig())
    solver.runtime_summary["n_cells"] = N_CELLS

    solver._run_steady_state_initialization()

    np.testing.assert_array_equal(solver.state.head_m, np.full(N_CELLS, 12.0))
    assert solver.runtime_summary["steady_mode"] == "recorded"
    assert solver.runtime_summary["n_cells"] == N_CELLS
    assert solver.runtime_summary["steady_state_initialization"] is True
    assert solver.runtime_summary["steady_state_initialization_solver"] == "boussinesq"


def test_the_solve_starts_from_the_state_of_the_main_solver(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[np.ndarray] = []

    def record(self: Boussinesq) -> bool:
        seen.append(np.array(self.state.head_m))
        return True

    monkeypatch.setattr(Boussinesq, "_run_steady_runtime", record)
    solver = _solver(tmp_path, _transient_model(), FlowRuntimeConfig())

    solver._run_steady_state_initialization()

    expected = np.full(N_CELLS, START_M)
    expected[0] = OUTLET_M
    np.testing.assert_array_equal(seen[0], expected)


def test_a_prescribed_rate_reaches_the_solve_on_every_period_and_not_the_model(
    tmp_path: Path, spy: list[dict]
) -> None:
    rate = 3.0e-9
    strategy = SteadyStateStrategy("prescribed", None, "first_period", rate)
    model = _transient_model(initial=SteadyStart(strategy))
    solver = _solver(tmp_path, model, FlowRuntimeConfig())

    solver._run_steady_state_initialization()

    assert spy[0]["first_clim"] == pytest.approx(rate)
    assert model.recharge.first_clim == 1.0e-9
    assert list(model.recharge.values) == [RECHARGE_M_S, 2 * RECHARGE_M_S, 0.0]


def test_a_failed_steady_solve_is_reported_and_leaves_the_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Boussinesq, "_run_steady_runtime", lambda self: False)
    model = _transient_model()
    solver = _solver(tmp_path, model, FlowRuntimeConfig())

    assert solver._run_steady_state_initialization() is False

    assert solver.runtime_summary["steady_state_initialization"] is False
    assert solver.inputs is model


def test_the_steady_solve_equals_the_stationary_solve_of_the_same_forcing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The auxiliary solve of a start is the steady solve of its forcing, from the top."""
    monkeypatch.setattr(steady_driver, "resolve_runtime_forcing_by_period", fixed_forcing((1e-8,)))
    runtime = FlowRuntimeConfig(backend="local", tol_residual_inf=1.0e-12)
    model = _transient_model()
    solver = _solver(tmp_path, model, runtime)
    before = repr(model)

    assert solver._run_steady_state_initialization() is True

    reference = _solver(
        tmp_path,
        make_model(time=ModelTime(grid=None, regime="steady", first_period_steady=True)),
        runtime,
        name="reference",
    )
    assert steady_driver.run_steady_runtime(reference)
    np.testing.assert_allclose(solver.state.head_m, reference.state.head_m, rtol=0.0, atol=1e-12)
    assert solver.runtime_summary["steady_mode"] == "nonlinear_local"
    assert solver.runtime_summary["steady_state_initialization"] is True
    assert repr(model) == before
