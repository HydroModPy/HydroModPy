"""A stage that already ran must be findable, not run again.

A staged calibration held what each stage froze in a Python list, so the whole
thing lived and died with one invocation. That is the wrong lifetime for the work:
stage one is a steady solve of minutes, stage two a daily chronicle over decades.
When the transient stage dies at hour six, the steady stage that succeeded goes
with it and the next attempt re-solves a result that was already correct.

Everything needed is on disk: a phase opens its own session row with its name and
its place in the chain, and every trial writes its parameters and its cost.
"""

from __future__ import annotations

import json

import pytest

from hydromodpy.calibration.runners.resume import (
    best_parameters_of,
    completed_phases,
    frozen_from_disk,
)
from hydromodpy.results.catalog import Catalog

_ROOT = "11111111-1111-1111-1111-111111111111"
_STEADY = "22222222-2222-2222-2222-222222222222"
_TRANSIENT = "33333333-3333-3333-3333-333333333333"


@pytest.fixture
def catalog(tmp_path):
    cat = Catalog(tmp_path / "index.duckdb")
    try:
        yield cat
    finally:
        cat.close()


def _session(catalog, session_id: str, *, phase: str, index: int, status: str) -> None:
    catalog._backend.execute(
        "INSERT INTO calibration_sessions "
        "(session_id, project, method, objective_name, n_iterations, config, started_at, "
        "status_id, root_session_id, phase_name, phase_index) "
        "VALUES (?, 'p', 'grid', 'nse', 0, '{}', current_timestamp, "
        "(SELECT id FROM statuses WHERE code = ?), ?, ?, ?)",
        [session_id, status, _ROOT, phase, index],
    )


def _trial(catalog, session_id: str, *, iteration: int, values: dict, cost: float) -> None:
    catalog._backend.execute(
        "INSERT INTO calibration_iterations "
        "(session_id, iteration, parameters, objective_value, status) "
        "VALUES (?, ?, ?, ?, 'completed')",
        [session_id, iteration, json.dumps(values), cost],
    )


class TestWhichPhasesFinished:
    def test_a_completed_phase_is_listed(self, catalog) -> None:
        _session(catalog, _STEADY, phase="steady_conductivity", index=0, status="completed")

        assert completed_phases(catalog, _ROOT) == {"steady_conductivity": _STEADY}

    def test_a_partial_phase_is_not(self, catalog) -> None:
        """It stopped mid-search; its best is not a value the stage settled on."""
        _session(catalog, _STEADY, phase="steady_conductivity", index=0, status="partial")

        assert completed_phases(catalog, _ROOT) == {}

    def test_a_phase_of_another_chain_is_not(self, catalog) -> None:
        _session(catalog, _STEADY, phase="steady_conductivity", index=0, status="completed")

        assert completed_phases(catalog, "99999999-9999-9999-9999-999999999999") == {}


class TestTheBestTrial:
    def test_it_is_the_smallest_finite_cost(self, catalog) -> None:
        _session(catalog, _STEADY, phase="steady_conductivity", index=0, status="completed")
        _trial(catalog, _STEADY, iteration=0, values={"K": 1e-4}, cost=9.0)
        _trial(catalog, _STEADY, iteration=1, values={"K": 3e-6}, cost=0.4)
        _trial(catalog, _STEADY, iteration=2, values={"K": 5e-5}, cost=3.0)

        assert best_parameters_of(catalog, _STEADY) == {"K": pytest.approx(3e-6)}

    def test_a_session_with_no_scored_trial_yields_nothing(self, catalog) -> None:
        _session(catalog, _STEADY, phase="steady_conductivity", index=0, status="completed")

        assert best_parameters_of(catalog, _STEADY) == {}


class TestWhatAStageFroze:
    def test_only_the_parameters_the_phase_could_move_are_frozen(self, catalog) -> None:
        """A trial records every parameter; a phase froze only the ones it calibrated."""
        _session(catalog, _STEADY, phase="steady_conductivity", index=0, status="completed")
        _trial(catalog, _STEADY, iteration=0, values={"K": 3e-6, "Sy": 0.05}, cost=0.4)

        found = frozen_from_disk(
            catalog, _ROOT, phases={"steady_conductivity": ("K",), "transient_storage": ("Sy",)}
        )

        assert found == {"steady_conductivity": {"K": pytest.approx(3e-6)}}

    def test_a_dead_transient_leaves_the_steady_stage_recoverable(self, catalog) -> None:
        """The case the whole thing exists for."""
        _session(catalog, _STEADY, phase="steady_conductivity", index=0, status="completed")
        _trial(catalog, _STEADY, iteration=0, values={"K": 3e-6}, cost=0.4)
        _session(catalog, _TRANSIENT, phase="transient_storage", index=1, status="failed")

        found = frozen_from_disk(
            catalog, _ROOT, phases={"steady_conductivity": ("K",), "transient_storage": ("Sy",)}
        )

        assert set(found) == {"steady_conductivity"}
        assert found["steady_conductivity"]["K"] == pytest.approx(3e-6)

    def test_a_phase_allowed_nothing_is_skipped(self, catalog) -> None:
        _session(catalog, _STEADY, phase="steady_conductivity", index=0, status="completed")
        _trial(catalog, _STEADY, iteration=0, values={"K": 3e-6}, cost=0.4)

        assert frozen_from_disk(catalog, _ROOT, phases={}) == {}
