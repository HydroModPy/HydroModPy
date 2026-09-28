"""A root search's bracket and two roots outlive the run, in ``session.json``.

The report carries ``extra["bracket"]`` and ``extra["roots"]`` in memory only.
The session journal keeps them under ``root_search``, so a card or a report
drawn later from the disk shows what the live run printed.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from hydromodpy.calibration.optim.optimizer import EvaluationResult, ParamSuggestion
from hydromodpy.calibration.persistence import CalibrationPersistence
from hydromodpy.calibration.runners.cli_runner import _root_search_record
from hydromodpy.results.catalog.reindex import rebuild_index
from hydromodpy.results.session_journal import (
    SESSION_JOURNAL_VERSION,
    SessionJournal,
    find_session_dir,
    read_descriptor,
    read_root_search,
)
from hydromodpy.results.storage.contract import SESSION_DESCRIPTOR_FILENAME
from tests._helpers.fixtures_catalog import simulation_catalog
from tests.unit.calibration.test_the_root_search_closes_one_root_per_bound import (
    _run,
    _two_bounds,
    _two_root_adapter,
)

ROOTS = {
    "parameter": "K",
    "minimal": {"k_star": 3.0e-6, "low": 2.9e-6, "high": 3.1e-6, "weight": 0.5},
    "maximal": {"k_star": 2.0e-4, "low": 1.9e-4, "high": 2.1e-4, "weight": 0.5},
    "delta_log10": 1.82,
    "value": 2.4e-5,
    "combined_trial_id": 23,
    "closed": True,
}


def _journal(
    project_root: Path,
    session_id: str,
    *,
    root_search: dict | None = None,
    root_session_id: str | None = None,
    phase_index: int | None = None,
) -> SessionJournal:
    journal = SessionJournal.start(
        project_root,
        session_id=session_id,
        project="demo",
        method="bisection",
        objective_name="distance_gap",
        search_space={"K": {"bounds": [1e-7, 1e-3]}},
        config={"method": "bisection"},
        started_at=datetime.now(UTC),
        root_session_id=root_session_id,
        parent_session_id=root_session_id,
        phase_index=phase_index,
    )
    journal.finish(
        status="completed",
        duration_s=1.0,
        ended_at=datetime.now(UTC),
        root_search=root_search,
    )
    return journal


def test_the_descriptor_keeps_the_two_roots(tmp_path: Path) -> None:
    journal = _journal(tmp_path, uuid.uuid4().hex, root_search={"roots": ROOTS})

    payload = json.loads((journal.directory / SESSION_DESCRIPTOR_FILENAME).read_text())

    assert payload["journal_version"] == SESSION_JOURNAL_VERSION == 3
    assert payload["root_search"] == {"roots": ROOTS}
    assert read_descriptor(journal.directory).root_search == {"roots": ROOTS}


def test_any_other_search_keeps_no_root_search(tmp_path: Path) -> None:
    journal = _journal(tmp_path, uuid.uuid4().hex)

    assert (
        json.loads((journal.directory / SESSION_DESCRIPTOR_FILENAME).read_text())["root_search"]
        is None
    )
    assert read_descriptor(journal.directory).root_search is None


def test_a_descriptor_written_before_the_key_reads_no_root_search(tmp_path: Path) -> None:
    journal = _journal(tmp_path, uuid.uuid4().hex, root_search={"roots": ROOTS})
    target = journal.directory / SESSION_DESCRIPTOR_FILENAME
    payload = json.loads(target.read_text())
    del payload["root_search"]
    payload["journal_version"] = 2
    target.write_text(json.dumps(payload))

    assert read_descriptor(journal.directory).root_search is None


def test_a_session_is_found_by_its_id_in_either_spelling(tmp_path: Path) -> None:
    session = uuid.uuid4()
    journal = _journal(tmp_path, session.hex, root_search={"bracket": {"low": 1.0}})
    _journal(tmp_path, uuid.uuid4().hex)

    assert find_session_dir(tmp_path, session.hex) == journal.directory
    assert find_session_dir(tmp_path, str(session)) == journal.directory
    assert find_session_dir(tmp_path, uuid.uuid4().hex) is None
    assert read_root_search(tmp_path, str(session)) == {"bracket": {"low": 1.0}}


def test_a_later_phase_reads_the_root_search_of_its_chain(tmp_path: Path) -> None:
    first = uuid.uuid4().hex
    second = uuid.uuid4().hex
    _journal(tmp_path, first, root_search={"roots": ROOTS}, root_session_id=first, phase_index=0)
    _journal(tmp_path, second, root_session_id=first, phase_index=1)

    assert read_root_search(tmp_path, second) == {"roots": ROOTS}
    assert read_root_search(tmp_path, first) == {"roots": ROOTS}


def test_no_session_on_disk_reads_no_root_search(tmp_path: Path) -> None:
    assert read_root_search(tmp_path, uuid.uuid4().hex) is None


def test_the_rebuild_indexes_a_session_that_kept_its_roots(tmp_path: Path) -> None:
    project = tmp_path / "demo"
    project.mkdir()
    session_id = uuid.uuid4().hex
    _journal(project, session_id, root_search={"roots": ROOTS})

    rebuilt = rebuild_index(project)

    assert rebuilt.rows["calibration_sessions"] == 1
    assert read_root_search(project, session_id) == {"roots": ROOTS}


def test_a_two_root_search_leaves_its_roots_in_session_json(tmp_path: Path) -> None:
    adapter = _two_root_adapter()
    session = _run(adapter, _two_bounds())
    record = _root_search_record(session)
    assert record == {"roots": adapter.roots_record()}

    session_id = uuid.uuid4().hex
    (tmp_path / "data").mkdir()
    with simulation_catalog(tmp_path) as catalog:
        persistence = CalibrationPersistence(catalog, project_root=tmp_path)
        persistence.start_session(
            session_id=session_id,
            project="demo",
            method="bisection",
            objective_name="distance_gap",
            search_space={"K": {"bounds": [1e-7, 1e-3]}},
            config={"method": "bisection"},
        )
        persistence.append_iteration(
            session_id,
            ParamSuggestion(trial_id=0, values={"K": 1e-5}),
            EvaluationResult(trial_id=0, sim_id=None, objective_value=0.1, status="completed"),
        )
        persistence.finalize_session(
            session_id,
            best=session.best,
            n_iterations=len(session.history),
            duration_s=1.0,
            root_search=record,
        )

    stored = read_root_search(tmp_path, session_id)
    assert stored is not None
    assert stored["roots"]["delta_log10"] == pytest.approx(record["roots"]["delta_log10"])
    assert stored["roots"]["combined_trial_id"] == record["roots"]["combined_trial_id"]
    assert stored["roots"]["minimal"]["k_star"] == pytest.approx(
        record["roots"]["minimal"]["k_star"]
    )


def test_a_search_that_is_no_root_search_publishes_no_record() -> None:
    assert _root_search_record(None) is None


def test_the_report_hands_the_journalled_roots_to_a_figure_that_takes_them(
    tmp_path: Path, monkeypatch
) -> None:
    import hydromodpy.reporting.calibration_report as report

    session_id = uuid.uuid4().hex
    journal = _journal(tmp_path, session_id, root_search={"roots": ROOTS})
    received: dict[str, dict] = {}

    class _Card:
        def plot(self, sim, *, save_path: Path, roots=None, **kwargs) -> None:
            received["card"] = {"roots": roots, **kwargs}
            Path(save_path).write_bytes(b"png")

    class _Trace:
        def plot(self, sim, *, save_path: Path, **kwargs) -> None:
            received["trace"] = kwargs
            Path(save_path).write_bytes(b"png")

    figures = {"card": _Card(), "trace": _Trace()}
    monkeypatch.setattr(report, "_figure_names", lambda: list(figures))
    monkeypatch.setattr(report, "_get_figure", figures.__getitem__)

    class _Payload:
        session_name = journal.directory.name
        session = {"session_id": session_id, "method": "bisection"}
        iterations = [{"iteration": 0, "objective_value": 0.1, "status": "completed"}]
        workspace_root = tmp_path
        best_sim_id = None
        sim_timeseries = None
        obs_timeseries = None
        variable = "discharge"

    _Payload.session_id = session_id
    report.render_session(_Payload(), figure_names=list(figures), output_dir=tmp_path / "out")

    assert received["card"]["roots"] == ROOTS
    assert "roots" not in received["trace"]
    assert received["trace"]["session_id"] == session_id
