"""The geometric seepage criterion must never replace a flux silently.

A solver that releases water through ``budget/surface_excess`` (Boussinesq)
has a physical seepage signal. Reading its store without that flux changes
the criterion to ``water table >= surface``, which over-reports: that
degradation is a WARNING, while the same geometric test on MODFLOW is the
criterion itself and stays quiet.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

import hydromodpy.core.field_routing as field_routing
from hydromodpy.core.field_routing import (
    SURFACE_EXCESS_STATE_GROUP,
    warn_on_geometric_seepage_fallback,
)


def _records(root: object) -> list[logging.LogRecord]:
    captured: list[logging.LogRecord] = []
    handler = logging.Handler()
    handler.emit = captured.append  # type: ignore[method-assign]
    field_routing.logger.addHandler(handler)
    try:
        warn_on_geometric_seepage_fallback(root, sim_id="sim-123")
    finally:
        field_routing.logger.removeHandler(handler)
    return captured


def test_surface_excess_solver_warns_on_the_geometric_fallback() -> None:
    captured = _records(_store(policy="consumers", kept_terms=["recharge"]))

    assert [record.levelno for record in captured] == [logging.WARNING]
    message = captured[0].getMessage()
    assert "sim-123" in message
    assert "surface_excess" in message
    assert "[simulation.results] keep_per_cell_budget = true" in message
    assert "spatial_fields" not in message


def test_modflow_store_stays_quiet() -> None:
    assert _records({"head": object(), "budget": object()}) == []


def test_non_mapping_root_is_ignored() -> None:
    assert _records(object()) == []


def _store(**budget_attrs: object) -> dict[str, object]:
    group = SimpleNamespace(attrs=dict(budget_attrs))
    return {SURFACE_EXCESS_STATE_GROUP: object(), "budget": group}


def test_a_store_without_policy_says_to_run_again() -> None:
    (record,) = _records({SURFACE_EXCESS_STATE_GROUP: object()})

    message = record.getMessage()
    assert "written before the per-cell budget was kept by default" in message
    assert "run it again" in message
    assert "keep_per_cell_budget" not in message


def test_a_consumers_store_names_its_terms_and_the_option() -> None:
    (record,) = _records(_store(policy="consumers", kept_terms=["drain", "recharge"]))

    message = record.getMessage()
    assert "(drain, recharge)" in message
    assert "[simulation.results] keep_per_cell_budget = true" in message


def test_an_all_store_has_no_option_to_offer() -> None:
    (record,) = _records(_store(policy="all", kept_terms=["recharge"]))

    message = record.getMessage()
    assert "produced no surface excess" in message
    assert "keep_per_cell_budget" not in message
