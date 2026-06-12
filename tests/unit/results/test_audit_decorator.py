"""Unit tests for the ``@audited`` decorator and its wiring."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from hydromodpy.results.catalog import Catalog
from hydromodpy.results.catalog.audit import audited
from tests._helpers.fixtures_catalog import simulation_catalog


@pytest.fixture
def catalog(tmp_path: Path) -> Catalog:
    with simulation_catalog(tmp_path / "ws") as cat:
        yield cat


def _register(catalog: Catalog, project: str = "lab") -> str:
    sid = str(uuid.uuid4())
    catalog.register_simulation(
        sid,
        project,
        "modflow6",
        name=f"sim-{sid[:8]}",
        n_cells=4,
        n_layers=1,
    )
    return sid


def test_audited_decorator_emits_event_after_method_returns() -> None:
    """The decorator emits one ``audit_log`` row matching ``event_type``."""
    emitted: list[dict] = []

    class _FakeDb:
        def execute(self, sql, params=None):
            emitted.append({"sql": sql, "params": params})
            return self

    class _Target:
        def __init__(self) -> None:
            self._db = _FakeDb()

        @audited("sim.register", payload_keys=("solver",))
        def do(self, sim_id: str, *, solver: str) -> str:
            return sim_id

    target = _Target()
    result = target.do("abc", solver="modflow6")
    assert result == "abc"
    assert emitted, "audit_log INSERT must be emitted"
    last = emitted[-1]
    params = last["params"]
    assert "audit_log" in last["sql"]
    assert "sim.register" in params
    assert "abc" in params
    payload_json = next(p for p in params if isinstance(p, str) and p.startswith("{"))
    assert json.loads(payload_json) == {"solver": "modflow6"}


def test_audited_decorator_does_not_raise_when_emit_fails() -> None:
    """A failing audit emission logs a warning but does not break the caller."""

    class _FailingDb:
        def execute(self, *_, **__):
            raise RuntimeError("db unavailable")

    class _Target:
        def __init__(self) -> None:
            self._db = _FailingDb()

        @audited("metric.write")
        def do(self, sim_id: str) -> str:
            return sim_id

    assert _Target().do("abc") == "abc"


def test_register_simulation_emits_sim_register(catalog: Catalog) -> None:
    """``register_simulation`` writes a ``sim.register`` row to audit_log."""
    sid = _register(catalog)
    rows = catalog.connection.execute(
        "SELECT event_type, sim_id, project, payload FROM audit_log "
        "WHERE sim_id = ? AND event_type = 'sim.register'",
        [sid],
    ).fetchall()
    assert len(rows) == 1
    _, log_sid, project, payload = rows[0]
    assert str(log_sid) == sid
    assert project == "lab"
    body = json.loads(payload)
    assert body["solver"] == "modflow6"


def test_finalize_emits_sim_finalize(catalog: Catalog) -> None:
    """``finalize`` writes a ``sim.finalize`` row to audit_log."""
    sid = _register(catalog)
    catalog.finalize(sid, status="completed")
    rows = catalog.connection.execute(
        "SELECT event_type, payload FROM audit_log "
        "WHERE sim_id = ? AND event_type = 'sim.finalize'",
        [sid],
    ).fetchall()
    assert len(rows) == 1
    _, payload = rows[0]
    body = json.loads(payload)
    assert body["status"] == "completed"


def test_write_parameters_emits_param_write(catalog: Catalog) -> None:
    """``write_parameters`` writes a ``param.write`` row to audit_log."""
    sid = _register(catalog)
    catalog.write_parameters(sid, [{"param_name": "k", "value": 1.0}])
    rows = catalog.connection.execute(
        "SELECT event_type FROM audit_log WHERE sim_id = ? AND event_type = 'param.write'",
        [sid],
    ).fetchall()
    assert len(rows) == 1


def test_write_metric_emits_metric_write(catalog: Catalog) -> None:
    """``write_metric`` writes a ``metric.write`` row to audit_log."""
    sid = _register(catalog)
    catalog.write_metric(sid, "__outlet__", "nse", 0.91)
    rows = catalog.connection.execute(
        "SELECT payload FROM audit_log WHERE sim_id = ? AND event_type = 'metric.write'",
        [sid],
    ).fetchall()
    assert len(rows) == 1
    payload = json.loads(rows[0][0])
    assert payload["metric_name"] == "nse"
    assert payload["value"] == 0.91
