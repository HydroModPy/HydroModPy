"""Unit tests for the GR4J calibration adapter (lumped, no solver binary).

``Gr4jAdapter`` is pure I/O wiring: it reads a simulated GR4J series back
either from the per-trial ``LumpedRamCache`` (hot path) or from a real
``Catalog`` (cold path). There is no GR4J production/routing
physics in this module, so these tests drive the *real* adapter against a
*real* DuckDB/Parquet catalog and a *real* RAM cache, and assert:

- round-trip fidelity of the stored series (machine-eps),
- survival of a water-balance closure built into the synthetic forcing,
- non-negativity of simulated flow and storage,
- the request-wiring / edge branches in ``extract_observables``
  and ``_latest_sim_id`` (the dark 90-124 block).

The science (mass conservation) lives in the synthetic series we build
from a short precip + PET forcing; the adapter is the object under test
and is never stubbed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import numpy as np
import pandas as pd
import pytest

import hydromodpy
from hydromodpy.calibration.lumped import Gr4jAdapter, LumpedRamCache, stash_series
from hydromodpy.calibration.lumped.gr4j_adapter import GR4J_SERIES_UNITS
from hydromodpy.core.contracts.observables import ObservableRequest
from hydromodpy.core.exceptions import ObservableNotAvailableError
from hydromodpy.core.state.run_state import WorkflowContext
from hydromodpy.simulation.planning.plan import ProcessRun, RunContext, SimulationPlan
from tests._helpers.fixtures_catalog import simulation_catalog
from tests._helpers.tolerances import tol

# Round-trip through Parquet/DuckDB is lossless for float64; allow only the
# documented machine-eps array tolerance (TOLERANCES.md row 15).
ATOL = tol("regression_goldens_arrays__atol")
# Water-balance closure tolerance: TOLERANCES.md global-budget row.
BUDGET_RTOL = tol("global_water_budget_closure__relative_error_in_out_in")


def _domain_request(
    name: str,
    *,
    request_id: str = "q",
    station: str | None = None,
) -> ObservableRequest:
    """Build the only request shape GR4J answers: a lumped domain series.

    The station travels in ``key`` and falls back to the outlet when absent.
    """
    return ObservableRequest(id=request_id, name=name, support="domain", key=station)


GR4J_RUN = ProcessRun(
    id="flow_main::gr4j",
    process_id="flow_main",
    process_type="flow",
    solver="gr4j",
)
GR4J_PLAN = SimulationPlan(name="gr4j", description="gr4j", runs=(GR4J_RUN,))


def _trial_context() -> WorkflowContext:
    """The pipeline runtime of a lumped calibration trial."""
    return WorkflowContext(cfg=None, config_path=Path("run_gr4j.toml"), raw_toml={})


def _ctx(trial: WorkflowContext | None = None) -> RunContext:
    """The context the adapter receives, built the way the pipeline builds it.

    Through ``RunContext.of`` on a real ``WorkflowContext``, so the double
    cannot serve a member the production path does not carry. A
    ``SimpleNamespace`` here would have hidden F8d entirely: ``RunState`` has
    ``slots``, and only a real one refuses a read of a scope it dropped.
    """
    return RunContext.of(trial or _trial_context(), plan=GR4J_PLAN, run=GR4J_RUN)


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
        trial = _trial_context()
        stash_series(trial.execution, "outlet", "discharge", run["outlet_discharge"])
        ctx = _ctx(trial)

        served = Gr4jAdapter().extract_observables(ctx, None, [_domain_request("discharge")])

        result = served["q"]
        np.testing.assert_allclose(result.values, run["outlet_discharge"].to_numpy(), atol=ATOL)
        assert result.request_id == "q"
        # The unit does not travel with the cached values, so the adapter
        # restates the one GR4J publishes for that series.
        assert result.units == "m3/s"

    def test_batch_serves_each_request_under_its_own_id(self, run):
        trial = _trial_context()
        stash_series(trial.execution, "outlet", "discharge", run["outlet_discharge"])
        stash_series(trial.execution, "outlet", "storage", run["outlet_storage"])
        ctx = _ctx(trial)

        served = Gr4jAdapter().extract_observables(
            ctx,
            None,
            [_domain_request("discharge"), _domain_request("storage", request_id="s")],
        )

        assert set(served) == {"q", "s"}
        assert served["q"].request_id == "q"
        assert served["s"].request_id == "s"
        np.testing.assert_allclose(
            served["q"].values, run["outlet_discharge"].to_numpy(), atol=ATOL
        )
        np.testing.assert_allclose(served["s"].values, run["outlet_storage"].to_numpy(), atol=ATOL)

    def test_time_index_reattached_when_lengths_match(self, run):
        trial = _trial_context()
        # Stash a values-only series (no index) to exercise reindexing.
        bare = pd.Series(run["outlet_discharge"].to_numpy())
        stash_series(trial.execution, "outlet", "discharge", bare)
        ctx = _ctx(trial)

        idx = run["outlet_discharge"].index
        result = Gr4jAdapter().extract_observables(
            ctx, None, [_domain_request("discharge")], time_index=idx
        )["q"]
        assert isinstance(result.times, pd.DatetimeIndex)
        assert result.times.equals(idx)

    def test_mismatched_time_index_falls_back_to_positional(self, run):
        trial = _trial_context()
        stash_series(trial.execution, "outlet", "discharge", run["outlet_discharge"])
        ctx = _ctx(trial)

        short_idx = run["outlet_discharge"].index[:5]
        result = Gr4jAdapter().extract_observables(
            ctx, None, [_domain_request("discharge")], time_index=short_idx
        )["q"]
        # Length mismatch -> positional series, no times, values intact.
        assert result.times is None
        np.testing.assert_allclose(result.values, run["outlet_discharge"].to_numpy(), atol=ATOL)

    def test_request_key_selects_station_id(self, run):
        trial = _trial_context()
        stash_series(trial.execution, "BV2", "discharge", run["outlet_discharge"])
        ctx = _ctx(trial)

        result = Gr4jAdapter().extract_observables(
            ctx, None, [_domain_request("discharge", station="BV2")]
        )["q"]
        np.testing.assert_allclose(result.values, run["outlet_discharge"].to_numpy(), atol=ATOL)

    def test_a_trial_that_stashed_nothing_is_refused_by_name(self, run):
        """No cache at all reads like no series, and says which one is missing.

        It used to raise ``NotImplementedError`` on a context whose execution
        scope was absent. That branch answered a question about the shape of
        the runtime, not about the data, and it was reachable only through a
        ``getattr`` default that swallowed the refusal of a slotted view.
        """
        with pytest.raises(KeyError, match="discharge"):
            Gr4jAdapter().extract_observables(_ctx(), None, [_domain_request("discharge")])

    def test_absent_series_raises_keyerror(self, run):
        trial = _trial_context()
        trial.execution.lumped_ram_cache = LumpedRamCache()
        ctx = _ctx(trial)
        with pytest.raises(KeyError):
            Gr4jAdapter().extract_observables(ctx, None, [_domain_request("discharge")])

    def test_empty_series_raises_keyerror(self):
        trial = _trial_context()
        stash_series(trial.execution, "outlet", "discharge", pd.Series(dtype=float))
        ctx = _ctx(trial)
        with pytest.raises(KeyError):
            Gr4jAdapter().extract_observables(ctx, None, [_domain_request("discharge")])


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
        ctx = _ctx()

        served = Gr4jAdapter().extract_observables(ctx, catalog, [_domain_request("discharge")])

        # Catalog returns rows ordered by timestep, so values line up 1:1.
        result = served["q"]
        np.testing.assert_allclose(result.values, run["outlet_discharge"].to_numpy(), atol=ATOL)
        assert result.request_id == "q"
        # The catalog unit is not read back either, and the answer is the same.
        assert result.units == "m3/s"

    def test_water_balance_survives_round_trip(self, catalog, run):
        self._persist(catalog, run)
        ctx = _ctx()
        adapter = Gr4jAdapter()

        # The catalog preserves insertion order (ORDER BY timestep), so the
        # round-tripped values line up positionally with the original series.
        q = adapter.extract_observables(ctx, catalog, [_domain_request("discharge")])["q"].values
        s = adapter.extract_observables(ctx, catalog, [_domain_request("storage")])["q"].values
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
        ctx = _ctx()
        adapter = Gr4jAdapter()
        q = adapter.extract_observables(ctx, catalog, [_domain_request("discharge")])["q"]
        store = adapter.extract_observables(ctx, catalog, [_domain_request("storage")])["q"]
        assert (q.values >= -ATOL).all()
        assert (store.values >= -ATOL).all()

    def test_time_index_reattached_when_lengths_match(self, catalog, run):
        self._persist(catalog, run)
        ctx = _ctx()
        idx = pd.date_range("2021-01-01", periods=len(run["outlet_discharge"]), freq="D")
        result = Gr4jAdapter().extract_observables(
            ctx, catalog, [_domain_request("discharge")], time_index=idx
        )["q"]
        assert result.times is not None
        assert result.times.equals(idx)

    def test_request_key_selects_station_id(self, catalog, run):
        self._persist(catalog, run, station_id="gauge_A")
        ctx = _ctx()
        result = Gr4jAdapter().extract_observables(
            ctx, catalog, [_domain_request("discharge", station="gauge_A")]
        )["q"]
        assert len(result.values) == len(run["outlet_discharge"])

    def test_an_unserved_variable_is_refused_by_name(self, catalog, run):
        # Refused on the unit it declares no value for, before the read: what a
        # user sees is the variable and the list of what GR4J publishes, not a
        # KeyError about a cache entry that was never going to be there.
        self._persist(catalog, run)
        ctx = _ctx()
        with pytest.raises(ObservableNotAvailableError, match="no unit for 'recharge'"):
            Gr4jAdapter().extract_observables(ctx, catalog, [_domain_request("recharge")])

    def test_no_simulation_in_store_raises_keyerror(self, catalog):
        ctx = _ctx()
        with pytest.raises(KeyError):
            Gr4jAdapter().extract_observables(ctx, catalog, [_domain_request("discharge")])

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

        ctx = _ctx()
        served = Gr4jAdapter().extract_observables(ctx, catalog, [_domain_request("discharge")])
        np.testing.assert_allclose(served["q"].values, expected.to_numpy(), atol=ATOL)


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


class TestTheUnitsGr4jDeclares:
    """An observable served unitless cannot be checked by the cost reading it.

    The map is not free to say anything: it has to be the unit the GR4J
    extractor writes beside the very same series, which is read off that file
    rather than restated here.
    """

    def test_the_declared_units_are_the_ones_the_extractor_writes(self):
        source = (
            Path(hydromodpy.__file__).parent / "calibration" / "lumped" / "gr4j_flow.py"
        ).read_text(encoding="utf-8")
        for variable, unit in GR4J_SERIES_UNITS.items():
            assert f'"{variable}", {variable}, unit="{unit}"' in source, variable

    def test_a_series_gr4j_declares_no_unit_for_is_refused_by_name(self, run):
        trial = _trial_context()
        stash_series(trial.execution, "outlet", "actual_evap", run["actual_evap"])
        ctx = _ctx(trial)

        with pytest.raises(ObservableNotAvailableError, match="actual_evap"):
            Gr4jAdapter().extract_observables(ctx, None, [_domain_request("actual_evap")])

    def test_storage_is_not_served_as_a_flow(self, run):
        trial = _trial_context()
        stash_series(trial.execution, "outlet", "storage", run["outlet_storage"])
        ctx = _ctx(trial)

        served = Gr4jAdapter().extract_observables(ctx, None, [_domain_request("storage")])
        assert served["q"].units == "mm"


class TestAdapterRunnerContract:
    """The runner-facing lifecycle hooks (validate/execute/cleanup)."""

    def test_execute_not_implemented(self):
        with pytest.raises(NotImplementedError):
            Gr4jAdapter().execute(_ctx())

    def test_validate_and_cleanup_are_noops(self):
        adapter = Gr4jAdapter()
        ctx = _ctx()
        assert adapter.validate(ctx) is None
        assert adapter.cleanup(ctx) is None

    def test_class_metadata(self):
        adapter = Gr4jAdapter()
        assert adapter.solver_name == "gr4j"
        assert adapter.process_type == "flow"
        assert adapter.requires == ()


def test_gr4j_refuses_a_support_it_cannot_have(ctx_factory=None):
    """GR4J is lumped: a cell or lake request is a declaration error, not a series."""
    from hydromodpy.core.contracts.observables import ObservableRequest
    from hydromodpy.core.exceptions import ObservableNotAvailableError

    request = ObservableRequest(id="h", name="head", support="cell", cell=(0, 0, 0))
    with pytest.raises(ObservableNotAvailableError, match="only 'domain'"):
        Gr4jAdapter().extract_observables(None, None, [request])
