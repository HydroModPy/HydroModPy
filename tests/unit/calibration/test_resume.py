"""``best_parameters_of`` must read the payload production actually writes.

``describe_values`` (``calibration/optim/parameters.py``) serializes each
parameter as ``{"value": ..., "target": ..., "units": ..., ...}``, and that is
what every trial persists to ``calibration_iterations.parameters``
(``calibration/persistence.py``). A reader that expects a bare number per
parameter cannot read a single real trial.
"""

from __future__ import annotations

import json

import pytest

from hydromodpy.calibration.runners.resume import best_parameters_of
from hydromodpy.results.catalog import Catalog

_STEADY = "22222222-2222-2222-2222-222222222222"


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
        [session_id, status, session_id, phase, index],
    )


def _trial(catalog, session_id: str, *, iteration: int, parameters: dict, cost: float) -> None:
    catalog._backend.execute(
        "INSERT INTO calibration_iterations "
        "(session_id, iteration, parameters, objective_value, status) "
        "VALUES (?, ?, ?, ?, 'completed')",
        [session_id, iteration, json.dumps(parameters), cost],
    )


class TestTheRealPayloadShape:
    def test_a_nested_entry_yields_its_value(self, catalog) -> None:
        """The shape every real trial writes: a mapping with 'value', 'target', 'units'."""
        _session(catalog, _STEADY, phase="steady_conductivity", index=0, status="completed")
        _trial(
            catalog,
            _STEADY,
            iteration=0,
            parameters={
                "K": {
                    "value": 1.33e-05,
                    "transformed_value": -4.88,
                    "bounds": [1e-06, 0.001],
                    "transform": "log",
                    "prior": "log_uniform",
                    "mode": "replace",
                    "target": "flow.param.K.field.value",
                    "units": "m/s",
                }
            },
            cost=0.4,
        )

        assert best_parameters_of(catalog, _STEADY) == {"K": pytest.approx(1.33e-05)}

    def test_a_bare_number_is_still_accepted(self, catalog) -> None:
        """A caller that wrote the flat form directly is not broken by the fix."""
        _session(catalog, _STEADY, phase="steady_conductivity", index=0, status="completed")
        _trial(catalog, _STEADY, iteration=0, parameters={"K": 3e-6}, cost=0.4)

        assert best_parameters_of(catalog, _STEADY) == {"K": pytest.approx(3e-6)}

    def test_an_entry_with_no_value_key_is_refused_by_name(self, catalog) -> None:
        _session(catalog, _STEADY, phase="steady_conductivity", index=0, status="completed")
        _trial(catalog, _STEADY, iteration=0, parameters={"K": {"target": "x"}}, cost=0.4)

        with pytest.raises(ValueError, match="K"):
            best_parameters_of(catalog, _STEADY)

    def test_an_unreadable_entry_is_refused_by_name(self, catalog) -> None:
        _session(catalog, _STEADY, phase="steady_conductivity", index=0, status="completed")
        _trial(catalog, _STEADY, iteration=0, parameters={"K": [1, 2]}, cost=0.4)

        with pytest.raises(ValueError, match="K"):
            best_parameters_of(catalog, _STEADY)
