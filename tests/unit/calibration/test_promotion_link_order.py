"""When a promoted run gets linked to the calibration that produced it.

A promoted run renders the figures of ``[display].figures`` as the last step of
its own pipeline. The figures about the calibration declare
``required_tables=("calibration_iterations",)``, and that gate answers by
asking the catalog whether any iteration row names this run. So the link has to
exist BEFORE the run replays, not after it: written after, every session figure
reports itself unavailable for a reason that stops being true one instruction
later, and the calibration can never produce its own figures.

The tests below observe the gate at render time, through a run-shaped stand-in
that answers ``has_table`` with the very query
:meth:`hydromodpy.results.run.Run.has_table` runs.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest

from hydromodpy.calibration.config import CalibrationConfig
from hydromodpy.calibration.optim import promotion as promotion_module
from hydromodpy.calibration.optim.promotion import promote_iterations
from hydromodpy.display import get as get_figure
from hydromodpy.results.catalog import Catalog

# The four figures of the stream-network method that read the session trials.
SESSION_FIGURES = (
    "downslope_distance_crossing",
    "bisection_bracket_trace",
    "parameter_cost_profile",
    "abherve_two_stage_card",
)

MISSING_TABLE_REASON = "missing catalog table(s): calibration_iterations"


class _RunAtRenderTime:
    """What the display step sees of a run while its pipeline is still going.

    Only the three members ``BaseFigure.unavailable_reason`` consults are
    implemented, and ``has_table`` runs the same query as the real ``Run``.
    """

    def __init__(self, catalog: Catalog, sim_id: str) -> None:
        self._catalog = catalog
        self._sim_id = sim_id
        self.solver = "modflow6"

    def has_field(self, field: str) -> bool:
        del field
        return False

    def has_table(self, table: str) -> bool:
        rows = self._catalog.connection.execute(
            f"SELECT 1 FROM {table} WHERE sim_id = ? LIMIT 1",  # noqa: S608 - fixed name
            [self._sim_id],
        ).fetchall()
        return bool(rows)


def _figure_reasons(catalog: Catalog, sim_id: str) -> dict[str, str | None]:
    """Return why each session figure could not draw that run, or None."""
    sim = _RunAtRenderTime(catalog, sim_id)
    return {name: get_figure(name).unavailable_reason(sim) for name in SESSION_FIGURES}


class _StubPersistence:
    """The three iteration rows a finished session offers for promotion."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def top_n(self, session_id: str, n: int) -> list[dict[str, Any]]:
        del session_id
        return self._rows[:n]

    def load_iterations(self, session_id: str) -> list[dict[str, Any]]:
        del session_id
        return list(self._rows)


def _rows() -> list[dict[str, Any]]:
    return [
        {
            "iteration": index,
            "parameters": {"K": 10.0**-index},
            "objective_value": float(index),
            "status": "completed",
        }
        for index in (1, 2, 3)
    ]


def _cfg(**updates: Any) -> CalibrationConfig:
    payload = {
        "method": "grid",
        "max_iter": 3,
        "save_runs": "best_n",
        "save_best_n": 2,
        "objective": "nse",
        "variable": "discharge",
        "use_cache": False,
        "rerun_best_with_outputs": False,
        "parameters": {
            "K": {
                "bounds": [1e-6, 1e-3],
                "transform": "log",
                "prior": "log_uniform",
                "path": "flow.param.K.field.value",
            }
        },
    }
    payload.update(updates)
    return CalibrationConfig.model_validate(payload)


@pytest.fixture
def session(tmp_path):
    """An open catalog holding the three iterations of one finished session."""
    session_id = str(uuid.uuid4())
    with Catalog(tmp_path) as catalog:
        for row in _rows():
            catalog.connection.execute(
                "INSERT INTO calibration_iterations "
                "(session_id, iteration, parameters, objective_value, status) "
                "VALUES (?, ?, ?, ?, 'completed')",
                [
                    uuid.UUID(session_id),
                    row["iteration"],
                    json.dumps(row["parameters"]),
                    row["objective_value"],
                ],
            )
        yield catalog, session_id


def _promote(catalog, session_id, monkeypatch, *, cfg=None, fail: bool = False):
    """Run the promotion with a fake pipeline that reports the gate it saw."""
    seen: dict[str, dict[str, str | None]] = {}

    def _fake_promote(trial_ctx, values, *, name=None, tags=(), session_id=None, sim_id=None):
        del trial_ctx, values, name, tags, session_id
        # A pipeline mints its own id when none was reserved, which is what the
        # promotion used to leave it to do.
        promoted = sim_id or str(uuid.uuid4())
        seen[promoted] = _figure_reasons(catalog, promoted)
        if fail:
            raise RuntimeError("solver did not converge")
        return promoted

    monkeypatch.setattr(promotion_module, "promote_prepared_trial", _fake_promote)
    result = promote_iterations(
        cfg=cfg or _cfg(),
        trial_ctx=object(),
        catalog=catalog,
        persistence=_StubPersistence(_rows()),
        session_id=session_id,
        best=None,
        override_paths={"K": "flow.param.K.field.value"},
    )
    return result, seen


def test_promoted_run_is_linked_before_it_renders(session, monkeypatch) -> None:
    catalog, session_id = session

    (count, failures, _), seen = _promote(catalog, session_id, monkeypatch)

    assert (count, failures) == (2, [])
    assert len(seen) == 2
    for sim_id, reasons in seen.items():
        assert reasons == dict.fromkeys(SESSION_FIGURES), (
            f"run {sim_id} was not linked to its session when it rendered"
        )


def test_link_survives_the_promotion(session, monkeypatch) -> None:
    catalog, session_id = session

    _, seen = _promote(catalog, session_id, monkeypatch)

    linked = catalog.connection.execute(
        "SELECT COUNT(*) FROM calibration_iterations WHERE session_id = ? AND sim_id IS NOT NULL",
        [uuid.UUID(session_id)],
    ).fetchone()
    assert linked[0] == 2
    assert set(_figure_reasons(catalog, next(iter(seen))).values()) == {None}


def test_a_failed_promotion_leaves_no_link(session, monkeypatch) -> None:
    catalog, session_id = session

    (count, failures, best_sim_id), seen = _promote(catalog, session_id, monkeypatch, fail=True)

    assert (count, best_sim_id) == (0, None)
    assert len(failures) == 2
    linked = catalog.connection.execute(
        "SELECT COUNT(*) FROM calibration_iterations WHERE session_id = ? AND sim_id IS NOT NULL",
        [uuid.UUID(session_id)],
    ).fetchone()
    assert linked[0] == 0
    for sim_id in seen:
        assert _figure_reasons(catalog, sim_id) == dict.fromkeys(
            SESSION_FIGURES, MISSING_TABLE_REASON
        )


def test_promoting_nothing_writes_nothing(session, monkeypatch) -> None:
    catalog, session_id = session

    result, seen = _promote(catalog, session_id, monkeypatch, cfg=_cfg(save_runs="none"))

    assert result == (0, [], None)
    assert seen == {}
    linked = catalog.connection.execute(
        "SELECT COUNT(*) FROM calibration_iterations WHERE session_id = ? AND sim_id IS NOT NULL",
        [uuid.UUID(session_id)],
    ).fetchone()
    assert linked[0] == 0


def test_a_run_outside_any_session_still_skips_with_its_sentence(session) -> None:
    catalog, _ = session

    reasons = _figure_reasons(catalog, str(uuid.uuid4()))

    assert reasons == dict.fromkeys(SESSION_FIGURES, MISSING_TABLE_REASON)
