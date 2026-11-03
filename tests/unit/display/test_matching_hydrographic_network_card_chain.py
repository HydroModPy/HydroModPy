"""The card of a promoted run draws every phase of the session it comes from.

A promoted run names its session, phase and trial in its seal. The session
journals the trials of every phase in ``sessions/<case>/trials.jsonl``. The
run promoted from the second phase of a protocol used to draw "Stage 1 -
transient_storage / Stage 2 - not run" and three empty panels. It reads the
first phase from the same journal and draws stage 1 with its bracket and
validity. The run promoted from the first phase, drawn before the second one
starts, names the second phase as the one that comes next.
"""

from __future__ import annotations

import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from hydromodpy.display.figures.matching_hydrographic_network_card import (
    MatchingHydrographicNetworkCard,
)
from hydromodpy.results.catalog import Catalog
from hydromodpy.results.catalog.indexer import rebuild_index
from hydromodpy.results.checks import CalibratedBy
from hydromodpy.results.run import Run
from hydromodpy.results.session.journal import append_trial
from hydromodpy.results.session.phase import PhaseDescriptor, write_phase
from hydromodpy.results.storage.contract import (
    RUN_RESOLVED_CONFIG_FILENAME,
    SESSION_CONFIG_FILENAME,
)
from tests._helpers.sealed_runs import make_project, seal_run, sealed_search, write_session_dir
from tests._helpers.session_documents import trial_line

from .test_matching_hydrographic_network_card import (
    _panel,
    _root_rows,
    _storage_rows,
    _texts,
)

SESSION = uuid.uuid4().hex
CASE = "nancon"
STEADY, STORAGE = "steady_conductivity", "transient_storage"
STARTED = datetime(2026, 9, 28, tzinfo=UTC)
# The session config freezes both phases, each with the metric it scores on,
# and the units of every parameter it moves.
SESSION_CONFIG = """\
[calibration.parameters.K_over_R]
units = "m/s"

[calibration.parameters.specific_yield]
units = "-"

[[calibration.phases]]
name = "steady_conductivity"
objective_blocks = [{ name = "steady_conductivity", metric = "distance_gap" }]

[[calibration.phases]]
name = "transient_storage"
objective_blocks = [{ name = "transient_storage", metric = "nse_log" }]
"""
SEARCH = {"phases": [{"name": STEADY}, {"name": STORAGE}]}


@pytest.fixture
def mpl():
    pytest.importorskip("matplotlib")
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    yield plt
    plt.close("all")


def _phase(project: Path, name: str, index: int) -> None:
    write_phase(
        project / "sessions" / CASE,
        PhaseDescriptor(
            phase_id=f"{SESSION[:8]}-{index}",
            name=name,
            index=index,
            status="completed",
            frozen={},
            restarts=0,
        ),
    )


def _trials(project: Path, phase: str, rows: list[dict], *, first: int) -> list[int]:
    """Journal *rows* as trials of *phase*, numbered from *first*; return the numbers."""
    numbers = []
    for offset, row in enumerate(rows):
        number = first + offset
        append_trial(
            project / "sessions" / CASE,
            trial_line(
                number,
                cost=row["cost"],
                case=CASE,
                phase=phase,
                status="completed" if row["status"] == "completed" else "crashed",
                params={name: entry["value"] for name, entry in row["parameters"].items()},
                components=row["components"],
                started_at=STARTED,
                ended_at=STARTED,
            ),
        )
        numbers.append(number)
    return numbers


def _promoted_run(project: Path, name: str, *, phase: str, trial: int) -> str:
    """Seal the run promoted from *trial* of *phase*, with the search it came out of."""
    sim_id = seal_run(
        project,
        name,
        project="p",
        calibrated_by=CalibratedBy(
            session_id=SESSION, phase=phase, trial=trial, session_status="completed"
        ),
    )
    shutil.copy(
        sealed_search(SEARCH) / RUN_RESOLVED_CONFIG_FILENAME,
        project / "runs" / name / RUN_RESOLVED_CONFIG_FILENAME,
    )
    return sim_id


def _open(project: Path, sim_id: str) -> tuple[Catalog, Run]:
    rebuild_index(project)
    catalog = Catalog(project)
    return catalog, Run(sim_id, catalog)


@pytest.fixture
def chain(tmp_path: Path) -> tuple[Path, str]:
    """A session whose first phase promoted a run; the second phase not yet run."""
    project = make_project(tmp_path / "p")
    write_session_dir(project, CASE, session_id=SESSION, trials=0, phases=(), status="completed")
    (project / "sessions" / CASE / SESSION_CONFIG_FILENAME).write_text(
        SESSION_CONFIG, encoding="utf-8"
    )
    _phase(project, STEADY, 0)
    numbers = _trials(project, STEADY, _root_rows(session_id=None), first=1)
    # The closed end of the bracket is the fourth trial, the promoted one.
    steady_run = _promoted_run(
        project, "nancon_steady_conductivity", phase=STEADY, trial=numbers[3]
    )
    return project, steady_run


def test_the_run_of_the_second_phase_draws_the_first_one(chain, mpl) -> None:
    project, _ = chain
    _phase(project, STORAGE, 1)
    numbers = _trials(project, STORAGE, _storage_rows(session_id=SESSION), first=5)
    storage_run = _promoted_run(
        project, "nancon_transient_storage", phase=STORAGE, trial=numbers[1]
    )
    catalog, run = _open(project, storage_run)

    fig = MatchingHydrographicNetworkCard().plot(run)

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
        catalog.close()


def test_the_run_of_the_first_phase_says_the_second_comes_next(chain, mpl) -> None:
    project, steady_run = chain
    catalog, run = _open(project, steady_run)

    fig = MatchingHydrographicNetworkCard().plot(run)

    try:
        assert _panel(fig, "Stage 1").get_title() == "Stage 1 - steady_conductivity"
        stage_two = _panel(fig, "Stage 2")
        assert stage_two.get_title() == "Stage 2 - transient_storage"
        assert "comes next" in _texts(stage_two)
        assert "not run" not in _texts(stage_two)
    finally:
        mpl.close(fig)
        catalog.close()
