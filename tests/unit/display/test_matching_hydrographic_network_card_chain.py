"""The card of a promoted run draws every phase of the chain it belongs to.

A promoted run carries the row of the one trial it was promoted from, and a
session read by that row is the session of that phase alone. The run promoted
from the second phase of a protocol used to draw "Stage 1 - transient_storage /
Stage 2 - not run" and three empty panels. It now reads the other sessions of
its chain from the index and draws stage 1 with its bracket and validity. The
run promoted from the first phase, drawn before the second one starts, names
the second phase as the one that comes next.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from hydromodpy.display.figures.matching_hydrographic_network_card import (
    MatchingHydrographicNetworkCard,
)
from hydromodpy.results.catalog import Catalog
from hydromodpy.results.run import Run

from .test_matching_hydrographic_network_card import (
    _panel,
    _root_rows,
    _storage_rows,
    _texts,
)

ROOT = str(uuid.uuid4())
STORAGE = str(uuid.uuid4())
PHASES = [{"name": "steady_conductivity"}, {"name": "transient_storage"}]


@pytest.fixture
def mpl():
    pytest.importorskip("matplotlib")
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    yield plt
    plt.close("all")


def _session(catalog, session_id: str, *, phase: str, index: int, units: str, metric: str):
    config = {
        "parameters": {"K_over_R" if index == 0 else "specific_yield": {"units": units}},
        "objective_blocks": [{"name": phase, "metric": metric}],
    }
    catalog.connection.execute(
        "INSERT INTO calibration_sessions (session_id, project, method, objective_name, "
        "config, started_at, root_session_id, parent_session_id, phase_name, phase_index) "
        "VALUES (?, 'p', 'bisection', 'nse', ?, ?, ?, ?, ?, ?)",
        [
            uuid.UUID(session_id),
            json.dumps(config),
            datetime(2026, 9, 28, tzinfo=UTC),
            uuid.UUID(ROOT),
            None if index == 0 else uuid.UUID(ROOT),
            phase,
            index,
        ],
    )


def _trials(catalog, session_id: str, rows: list[dict], *, promoted: str | None, best: int):
    for row in rows:
        catalog.connection.execute(
            "INSERT INTO calibration_iterations (session_id, iteration, sim_id, parameters, "
            "objective_value, metrics, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                uuid.UUID(session_id),
                row["iteration"],
                uuid.UUID(promoted) if promoted and row["iteration"] == best else None,
                json.dumps(row["parameters"]),
                row["objective_value"],
                json.dumps(row["metrics"]),
                row["status"] if row["status"] == "completed" else "crashed",
            ],
        )


def _promoted_run(catalog, name: str) -> str:
    sid = str(uuid.uuid4())
    catalog.register_simulation(
        sid,
        project="p",
        solver="modflow6",
        name=name,
        config={"calibration": {"phases": PHASES}},
        config_snapshot={"calibration": {"phases": PHASES}},
    )
    return sid


@pytest.fixture
def chain(tmp_path: Path):
    with Catalog(tmp_path) as catalog:
        _session(
            catalog, ROOT, phase="steady_conductivity", index=0, units="m/s", metric="distance_gap"
        )
        steady_run = _promoted_run(catalog, "nancon_steady_conductivity")
        # The closed end of the bracket is trial 3, the promoted one.
        _trials(catalog, ROOT, _root_rows(session_id=None), promoted=steady_run, best=3)
        yield catalog, steady_run


def test_the_run_of_the_second_phase_draws_the_first_one(chain, mpl) -> None:
    catalog, _ = chain
    _session(catalog, STORAGE, phase="transient_storage", index=1, units="-", metric="nse_log")
    storage_run = _promoted_run(catalog, "nancon_transient_storage")
    _trials(catalog, STORAGE, _storage_rows(session_id=STORAGE), promoted=storage_run, best=1)

    fig = MatchingHydrographicNetworkCard().plot(Run(storage_run, catalog))

    try:
        stage_one = _panel(fig, "Stage 1")
        assert stage_one.get_title() == "Stage 1 - steady_conductivity"
        assert stage_one.get_xlabel() == "K_over_R (m/s)"
        assert "closed on K_over_R = 3.2e-05" in _texts(stage_one)
        stage_two = _panel(fig, "Stage 2")
        assert stage_two.get_title() == "Stage 2 - transient_storage"
        assert stage_two.get_ylabel() == "cost, nse_log (-)"
        validity = _panel(fig, "Validity of the agreement")
        assert validity.patches, "the validity of stage 1 is drawn, not left empty"
    finally:
        mpl.close(fig)


def test_the_run_of_the_first_phase_says_the_second_comes_next(chain, mpl) -> None:
    catalog, steady_run = chain

    fig = MatchingHydrographicNetworkCard().plot(Run(steady_run, catalog))

    try:
        assert _panel(fig, "Stage 1").get_title() == "Stage 1 - steady_conductivity"
        stage_two = _panel(fig, "Stage 2")
        assert stage_two.get_title() == "Stage 2 - transient_storage"
        assert "comes next" in _texts(stage_two)
        assert "not run" not in _texts(stage_two)
    finally:
        mpl.close(fig)
