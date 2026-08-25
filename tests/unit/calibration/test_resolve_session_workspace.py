"""Federation tests for ``resolve_session_in_workspace``.

``hmp report render`` must reach a calibration session wherever it lives in a
workspace: the workspace-level catalog or any ``projects/<name>`` catalog, like
``hmp catalog ls``. It must also accept a calibration run id (an iteration or
the promoted best run, as printed by ``ls``) and map it to its parent session.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from hydromodpy.calibration.optim.optimizer import EvaluationResult, ParamSuggestion
from hydromodpy.calibration.persistence import CalibrationPersistence
from hydromodpy.calibration.report import resolve_session_in_workspace
from hydromodpy.core.exceptions import ConfigError, ConfigMissingError
from tests._helpers.fixtures_catalog import simulation_catalog

pytestmark = pytest.mark.fast


def _mk(prefix: str, tail: str) -> str:
    """Build a 32-hex id with a controlled prefix and tail for deterministic matching."""
    body = prefix + "0" * (32 - len(prefix) - len(tail)) + tail
    assert len(body) == 32
    return body


SID_A = _mk("abcd1111", "0a01")  # session in projA, shares 'abcd' with SIM_B1
SID_B = _mk("bbbbbbbb", "0b02")  # session in projB
SIM_A1 = _mk("11111111", "0a01")  # projA iteration runs share '11111111'
SIM_A2 = _mk("11111111", "0a02")
SIM_B1 = _mk("abcd2222", "0b01")  # projB best run, shares 'abcd' with SID_A


def _seed_session(
    root: Path,
    *,
    session_id: str,
    project: str,
    sim_ids: list[str],
    started_at: datetime | None = None,
) -> None:
    """Create one calibration session with iterations carrying real sim ids."""
    import uuid

    root.mkdir(parents=True, exist_ok=True)
    (root / "data").mkdir(exist_ok=True)
    with simulation_catalog(root) as cat:
        persistence = CalibrationPersistence(cat)
        persistence.start_session(
            session_id=session_id,
            project=project,
            method="optuna",
            objective_name="nse",
            search_space={"K": {"bounds": [1e-5, 1e-3]}},
            config={"max_iter": len(sim_ids)},
        )
        for i, sim_hex in enumerate(sim_ids):
            persistence.append_iteration(
                session_id,
                ParamSuggestion(trial_id=i, values={"K": 1e-4 * (i + 1)}),
                EvaluationResult(
                    trial_id=i,
                    sim_id=sim_hex,
                    objective_value=0.5 - 0.1 * i,
                    status="completed",
                    duration_s=0.1,
                    components={"nse": 0.5 - 0.1 * i},
                ),
            )
        persistence.finalize_session(
            session_id,
            best=EvaluationResult(
                trial_id=0, sim_id=sim_ids[0], objective_value=0.5, status="completed"
            ),
            n_iterations=len(sim_ids),
            duration_s=0.3,
        )
        if started_at is not None:
            cat.connection.execute(
                "UPDATE calibration_sessions SET started_at = ? WHERE session_id = ?",
                [started_at, uuid.UUID(session_id)],
            )


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    """A workspace with an empty top-level catalog and two project catalogs."""
    ws = tmp_path
    (ws / "data").mkdir(exist_ok=True)
    with simulation_catalog(ws):  # empty workspace-level catalog, like examples/
        pass
    _seed_session(
        ws / "projects" / "projA",
        session_id=SID_A,
        project="projA",
        sim_ids=[SIM_A1, SIM_A2],
        started_at=datetime(2020, 1, 1, tzinfo=UTC),
    )
    _seed_session(
        ws / "projects" / "projB",
        session_id=SID_B,
        project="projB",
        sim_ids=[SIM_B1],
        started_at=datetime(2021, 1, 1, tzinfo=UTC),
    )
    return ws


def test_session_prefix_resolves_to_owning_project(workspace: Path) -> None:
    root, sid = resolve_session_in_workspace(workspace, "abcd1111")
    assert root.name == "projA"
    assert sid == SID_A
    root, sid = resolve_session_in_workspace(workspace, "bbbbbbbb")
    assert root.name == "projB"
    assert sid == SID_B


def test_full_run_id_maps_to_parent_session(workspace: Path) -> None:
    root, sid = resolve_session_in_workspace(workspace, SIM_A2)
    assert root.name == "projA"
    assert sid == SID_A


def test_run_id_prefix_shared_by_iterations_of_one_session(workspace: Path) -> None:
    # '11111111' matches both projA iteration runs; both map to the same session.
    root, sid = resolve_session_in_workspace(workspace, "11111111")
    assert (root.name, sid) == ("projA", SID_A)


def test_none_returns_most_recent_across_workspace(workspace: Path) -> None:
    root, sid = resolve_session_in_workspace(workspace, None)
    assert root.name == "projB"  # started_at 2021 > 2020
    assert sid == SID_B


def test_ambiguous_reference_across_projects_raises(workspace: Path) -> None:
    # 'abcd' matches session SID_A (projA) and run SIM_B1 -> SID_B (projB).
    with pytest.raises(ConfigError, match="ambiguous"):
        resolve_session_in_workspace(workspace, "abcd")


def test_no_match_raises_missing(workspace: Path) -> None:
    with pytest.raises(ConfigMissingError, match="No calibration session or run"):
        resolve_session_in_workspace(workspace, "deadbeef")


def test_single_catalog_workspace_preserves_project_scope(tmp_path: Path) -> None:
    proj = tmp_path / "solo"
    _seed_session(proj, session_id=SID_A, project="solo", sim_ids=[SIM_A1])
    root, sid = resolve_session_in_workspace(proj, SID_A)
    assert root == proj.resolve()
    assert sid == SID_A


def test_empty_single_catalog_raises_legacy_message(tmp_path: Path) -> None:
    (tmp_path / "data").mkdir(exist_ok=True)
    with simulation_catalog(tmp_path):  # catalog with no sessions
        pass
    with pytest.raises(ConfigMissingError, match="No calibration session found"):
        resolve_session_in_workspace(tmp_path, None)
