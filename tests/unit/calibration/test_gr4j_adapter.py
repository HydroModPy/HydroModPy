"""Unit tests for the GR4J calibration adapter (lumped, no solver binary).

``Gr4jAdapter`` is pure I/O wiring: it reads a simulated GR4J series back
either from the per-trial ``LumpedRamCache`` (hot path) or from a real
``Catalog`` (cold path). There is no GR4J production/routing
physics in this module, so these tests drive the *real* adapter against a
*real* DuckDB/Parquet catalog and a *real* RAM cache, and assert:

- round-trip fidelity of the stored series (machine-eps),
- survival of a water-balance closure built into the synthetic forcing,
- non-negativity of simulated flow and storage,
- the parameter-wiring / edge branches in ``extract_calibration_series``
  and ``_latest_sim_id`` (the dark 90-124 block).

The science (mass conservation) lives in the synthetic series we build
from a short precip + PET forcing; the adapter is the object under test
and is never stubbed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import numpy as np
import pandas as pd
import pytest

from hydromodpy.calibration.lumped import Gr4jAdapter, LumpedRamCache, stash_series
from tests._helpers.fixtures_catalog import simulation_catalog
from tests._helpers.tolerances import tol

# Round-trip through Parquet/DuckDB is lossless for float64; allow only the
# documented machine-eps array tolerance (TOLERANCES.md row 15).
ATOL = tol("regression_goldens_arrays__atol")
# Water-balance closure tolerance: TOLERANCES.md global-budget row.
BUDGET_RTOL = tol("global_water_budget_closure__relative_error_in_out_in")


@dataclass
class _FakeExecution:
    """Stand-in for the trial execution registry the adapter reads from."""

    lumped_ram_cache: LumpedRamCache | None = None


@dataclass
class _FakeState:
    execution: Any = None


@dataclass
class _FakeCtx:
    """Minimal RunContext-shaped object: only ``.state.execution`` is read."""

    state: Any = field(default_factory=_FakeState)


def _synthetic_gr4j_run(n: int = 40) -> dict[str, pd.Series]:
    """Build a short GR4J-like run from a synthetic precip + PET forcing.

    The water balance ``dS = P - E - Q`` holds by construction at every
    step, so the closure assertion below is a genuine physical invariant
    on the series the adapter round-trips, not a tautology.
    """
    idx = pd.date_range("2021-01-01", periods=n, freq="D")
    rng = np.random.default_rng(7)
    precip = pd.Series(rng.gamma(shape=1.5, scale=2.0, size=n), index=idx, name="precip")
    pet = pd.Series(np.full(n, 1.2), index=idx, name="pet")

    # Linear-reservoir production+routing: a deliberately simple but
    # mass-conserving surrogate of GR4J's store dynamics.
    store = np.zeros(n)
    discharge = np.zeros(n)
    actual_evap = np.zeros(n)
    s = 50.0  # initial storage [mm]
    for t in range(n):
        evap = min(pet.iloc[t], s)  # cannot evaporate more than is stored
        s_after_pe = s + precip.iloc[t] - evap
        q = 0.15 * s_after_pe  # linear outflow
        s_next = s_after_pe - q
        actual_evap[t] = evap
        discharge[t] = q
        store[t] = s_next
        s = s_next

    return {
        "outlet_discharge": pd.Series(discharge, index=idx, name="discharge"),
        "outlet_storage": pd.Series(store, index=idx, name="storage"),
        "precip": precip,
        "pet": pet,
        "actual_evap": pd.Series(actual_evap, index=idx, name="actual_evap"),
        "initial_storage": 50.0,
    }


@pytest.fixture
def run() -> dict[str, pd.Series]:
    return _synthetic_gr4j_run()


@pytest.fixture
def catalog(tmp_path):
    with simulation_catalog(tmp_path / "workspace") as cat:
        yield cat


class TestSyntheticForcingInvariants:
    """The forcing series itself must satisfy the physics we later assert."""

    def test_mass_conservation_of_forcing(self, run):
        precip = run["precip"].to_numpy()
        evap = run["actual_evap"].to_numpy()
        q = run["outlet_discharge"].to_numpy()
        store = run["outlet_storage"].to_numpy()

        s_prev = np.concatenate([[run["initial_storage"]], store[:-1]])
        dS = store - s_prev
        residual = dS - (precip - evap - q)
        assert np.max(np.abs(residual)) <= ATOL

    def test_non_negativity_of_state_and_flux(self, run):
        assert (run["outlet_discharge"].to_numpy() >= 0).all()
        assert (run["outlet_storage"].to_numpy() >= 0).all()
        assert (run["actual_evap"].to_numpy() >= 0).all()


class TestHotPathRamCache:
    """store=None: read the series the runner stashed in LumpedRamCache."""

    def test_round_trip_preserves_values(self, run):
        execution = _FakeExecution()
        stash_series(execution, "outlet", "discharge", run["outlet_discharge"])
        ctx = _FakeCtx(state=_FakeState(execution=execution))

        out = Gr4jAdapter().extract_calibration_series(ctx, None, variable="discharge")

        np.testing.assert_allclose(out.to_numpy(), run["outlet_discharge"].to_numpy(), atol=ATOL)
        assert out.name == "discharge"

    def test_time_index_reattached_when_lengths_match(self, run):
        execution = _FakeExecution()
        # Stash a values-only series (no index) to exercise reindexing.
        bare = pd.Series(run["outlet_discharge"].to_numpy())
        stash_series(execution, "outlet", "discharge", bare)
        ctx = _FakeCtx(state=_FakeState(execution=execution))

        idx = run["outlet_discharge"].index
        out = Gr4jAdapter().extract_calibration_series(
            ctx, None, variable="discharge", time_index=idx
        )
        assert isinstance(out.index, pd.DatetimeIndex)
        assert out.index.equals(idx)

    def test_mismatched_time_index_falls_back_to_positional(self, run):
        execution = _FakeExecution()
        stash_series(execution, "outlet", "discharge", run["outlet_discharge"])
        ctx = _FakeCtx(state=_FakeState(execution=execution))

        short_idx = run["outlet_discharge"].index[:5]
        out = Gr4jAdapter().extract_calibration_series(
            ctx, None, variable="discharge", time_index=short_idx
        )
        # Length mismatch -> positional RangeIndex, values intact.
        assert isinstance(out.index, pd.RangeIndex)
        np.testing.assert_allclose(out.to_numpy(), run["outlet_discharge"].to_numpy(), atol=ATOL)

    def test_station_cells_selects_station_id(self, run):
        execution = _FakeExecution()
        stash_series(execution, "BV2", "discharge", run["outlet_discharge"])
        ctx = _FakeCtx(state=_FakeState(execution=execution))

        out = Gr4jAdapter().extract_calibration_series(
            ctx, None, variable="discharge", station_cells={"BV2": (0, 0, 0)}
        )
        np.testing.assert_allclose(out.to_numpy(), run["outlet_discharge"].to_numpy(), atol=ATOL)

    def test_missing_execution_state_raises(self, run):
        ctx = _FakeCtx(state=_FakeState(execution=None))
        with pytest.raises(NotImplementedError):
            Gr4jAdapter().extract_calibration_series(ctx, None, variable="discharge")

    def test_absent_series_raises_keyerror(self, run):
        execution = _FakeExecution(lumped_ram_cache=LumpedRamCache())
        ctx = _FakeCtx(state=_FakeState(execution=execution))
        with pytest.raises(KeyError):
            Gr4jAdapter().extract_calibration_series(ctx, None, variable="discharge")

    def test_empty_series_raises_keyerror(self):
        execution = _FakeExecution()
        stash_series(execution, "outlet", "discharge", pd.Series(dtype=float))
        ctx = _FakeCtx(state=_FakeState(execution=execution))
        with pytest.raises(KeyError):
            Gr4jAdapter().extract_calibration_series(ctx, None, variable="discharge")


class TestColdPathCatalog:
    """store non-None: round-trip through a real Catalog."""

    def _persist(self, catalog, run, *, station_id="outlet", solver="gr4j"):
        sid = str(uuid4())
        catalog.register_simulation(sid, project="test", solver=solver)
        catalog.write_timeseries(sid, station_id, "discharge", run["outlet_discharge"], unit="m3/s")
        catalog.write_timeseries(sid, station_id, "storage", run["outlet_storage"], unit="mm")
        return sid

    def test_round_trip_preserves_values(self, catalog, run):
        self._persist(catalog, run)
        ctx = _FakeCtx()

        out = Gr4jAdapter().extract_calibration_series(ctx, catalog, variable="discharge")

        # Catalog returns rows ordered by timestep, so values line up 1:1.
        np.testing.assert_allclose(out.to_numpy(), run["outlet_discharge"].to_numpy(), atol=ATOL)
        assert out.name == "discharge"

    def test_water_balance_survives_round_trip(self, catalog, run):
        self._persist(catalog, run)
        ctx = _FakeCtx()
        adapter = Gr4jAdapter()

        # The catalog preserves insertion order (ORDER BY timestep), so the
        # round-tripped values line up positionally with the original series.
        q = adapter.extract_calibration_series(ctx, catalog, variable="discharge").to_numpy()
        s = adapter.extract_calibration_series(ctx, catalog, variable="storage").to_numpy()
        precip = run["precip"].to_numpy()
        evap = run["actual_evap"].to_numpy()

        s_prev = np.concatenate([[run["initial_storage"]], s[:-1]])
        dS = s - s_prev
        inflow = precip
        outflow = evap + q
        total_in = inflow.sum()
        residual = (dS - (inflow - outflow)).sum()
        assert total_in > 0
        assert abs(residual) <= BUDGET_RTOL * total_in

    def test_round_trip_non_negativity(self, catalog, run):
        self._persist(catalog, run)
        ctx = _FakeCtx()
        adapter = Gr4jAdapter()
        q = adapter.extract_calibration_series(ctx, catalog, variable="discharge")
        store = adapter.extract_calibration_series(ctx, catalog, variable="storage")
        assert (q.to_numpy() >= -ATOL).all()
        assert (store.to_numpy() >= -ATOL).all()

    def test_time_index_reattached_when_lengths_match(self, catalog, run):
        self._persist(catalog, run)
        ctx = _FakeCtx()
        idx = pd.RangeIndex(len(run["outlet_discharge"]))
        out = Gr4jAdapter().extract_calibration_series(
            ctx, catalog, variable="discharge", time_index=idx
        )
        assert out.index.equals(idx)

    def test_station_cells_selects_station_id(self, catalog, run):
        self._persist(catalog, run, station_id="gauge_A")
        ctx = _FakeCtx()
        out = Gr4jAdapter().extract_calibration_series(
            ctx, catalog, variable="discharge", station_cells={"gauge_A": (0, 0, 0)}
        )
        assert len(out) == len(run["outlet_discharge"])

    def test_unknown_variable_raises_keyerror(self, catalog, run):
        self._persist(catalog, run)
        ctx = _FakeCtx()
        with pytest.raises(KeyError):
            Gr4jAdapter().extract_calibration_series(ctx, catalog, variable="recharge")

    def test_no_simulation_in_store_raises_keyerror(self, catalog):
        ctx = _FakeCtx()
        with pytest.raises(KeyError):
            Gr4jAdapter().extract_calibration_series(ctx, catalog, variable="discharge")

    def test_latest_sim_id_matches_catalog_listing_tail(self, catalog, run):
        # With two GR4J sims, the adapter reads whichever sim_id the catalog
        # listing puts last (list_simulations orders by sim_id, NOT by
        # registration time). The series read back must belong to that sim,
        # so we cross-check against the catalog's own iloc[-1].
        sid_a = self._persist(catalog, run)
        scaled = {k: (v * 3.0 if isinstance(v, pd.Series) else v) for k, v in run.items()}
        sid_b = self._persist(catalog, scaled)
        assert sid_a != sid_b

        expected_sid = str(catalog.list_simulations(solver="gr4j").iloc[-1]["sim_id"])
        expected = catalog.query_timeseries(expected_sid, "outlet", "discharge")

        ctx = _FakeCtx()
        out = Gr4jAdapter().extract_calibration_series(ctx, catalog, variable="discharge")
        np.testing.assert_allclose(out.to_numpy(), expected.to_numpy(), atol=ATOL)


class TestLatestSimIdEdgeBranches:
    """Direct coverage of the _latest_sim_id helper (dark 110-124)."""

    def test_store_without_list_simulations_returns_none(self):
        store = SimpleNamespace()  # no list_simulations attribute
        assert Gr4jAdapter._latest_sim_id(store) is None

    def test_empty_listing_returns_none(self):
        store = SimpleNamespace(list_simulations=lambda **kw: pd.DataFrame())
        assert Gr4jAdapter._latest_sim_id(store) is None

    def test_none_listing_returns_none(self):
        store = SimpleNamespace(list_simulations=lambda **kw: None)
        assert Gr4jAdapter._latest_sim_id(store) is None

    def test_solver_filter_used_when_supported(self):
        calls: list[dict] = []

        def list_simulations(**kw):
            calls.append(kw)
            return pd.DataFrame({"sim_id": ["a", "b", "z9"]})

        store = SimpleNamespace(list_simulations=list_simulations)
        assert Gr4jAdapter._latest_sim_id(store) == "z9"
        assert calls and calls[0].get("solver") == "gr4j"

    def test_typeerror_falls_back_to_no_filter(self):
        calls: list[tuple] = []

        def list_simulations(*args, **kw):
            calls.append((args, kw))
            if kw.get("solver") is not None:
                raise TypeError("unexpected keyword 'solver'")
            return pd.DataFrame({"sim_id": ["only"]})

        store = SimpleNamespace(list_simulations=list_simulations)
        assert Gr4jAdapter._latest_sim_id(store) == "only"
        # First call passed solver=, second fell back to no kwargs.
        assert len(calls) == 2

    def test_other_exception_wrapped_as_runtimeerror(self):
        def list_simulations(**kw):
            raise ValueError("backend down")

        store = SimpleNamespace(list_simulations=list_simulations)
        with pytest.raises(RuntimeError):
            Gr4jAdapter._latest_sim_id(store)

    def test_missing_sim_id_column_returns_none(self):
        store = SimpleNamespace(list_simulations=lambda **kw: pd.DataFrame({"other_col": [1, 2]}))
        assert Gr4jAdapter._latest_sim_id(store) is None


class TestAdapterRunnerContract:
    """The runner-facing lifecycle hooks (validate/execute/cleanup)."""

    def test_execute_not_implemented(self):
        with pytest.raises(NotImplementedError):
            Gr4jAdapter().execute(_FakeCtx())

    def test_validate_and_cleanup_are_noops(self):
        adapter = Gr4jAdapter()
        ctx = _FakeCtx()
        assert adapter.validate(ctx) is None
        assert adapter.cleanup(ctx) is None

    def test_class_metadata(self):
        adapter = Gr4jAdapter()
        assert adapter.solver_name == "gr4j"
        assert adapter.process_type == "flow"
        assert adapter.requires == ()
