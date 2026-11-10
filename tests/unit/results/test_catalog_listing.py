"""The listing functions of ``hmp catalog`` answer from the index of an indexed project."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import duckdb
import pandas as pd
import pytest

from hydromodpy.core.state.layout import PROJECTS_DIRNAME, WORKSPACE_TOML_FILENAME
from hydromodpy.results.catalog import rebuild_index
from hydromodpy.results.catalog.listing import (
    NO_PROFILE_TEXT,
    SEALED_SOLVE_METRIC,
    diff_simulations,
    list_simulations,
    profile_of_run,
    query_catalog,
    show_simulation,
    solve_seconds,
)
from hydromodpy.results.record.manifest import MetricRow
from hydromodpy.results.record.record import RunRecord
from hydromodpy.results.storage.run_profile import Profile, ProfileLine, write_profile
from tests._helpers.sealed_runs import make_project, seal_run


def _seed_workspace(tmp_path: Path) -> tuple[Path, Path, str]:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / WORKSPACE_TOML_FILENAME).write_text("[workspace]\n", encoding="utf-8")
    project_dir = make_project(workspace / PROJECTS_DIRNAME / "demo")
    sim_id = seal_run(project_dir, "baseline", solver="modflow_nwt", nse=0.6, tags=("pinned",))
    seal_run(project_dir, "variant", solver="modflow6", nse=0.8, parameters={"K": 3e-5})
    rebuild_index(project_dir)
    return workspace, project_dir, sim_id


def test_list_simulations_returns_one_row_per_sealed_run(tmp_path: Path) -> None:
    workspace, _project, sim_id = _seed_workspace(tmp_path)

    df = list_simulations(workspace)

    assert isinstance(df, pd.DataFrame)
    assert sim_id in df["sim_id"].tolist()
    assert set(df["name"]) == {"baseline", "variant"}
    assert set(df["project"]) == {"demo"}
    assert {"site", "case_id", "rel_dir", "label", "nse"} <= set(df.columns)


def test_list_simulations_filters(tmp_path: Path) -> None:
    workspace, _project, _sim_id = _seed_workspace(tmp_path)

    # One name per backend: a shorthand of it names nothing.
    assert list_simulations(workspace, solver="nwt").empty
    assert list_simulations(workspace, solver="modflow_nwt")["name"].tolist() == ["baseline"]
    assert list_simulations(workspace, tag="pinned")["name"].tolist() == ["baseline"]
    assert list_simulations(workspace, label="exploratory").shape[0] == 2
    assert list_simulations(workspace, site="nowhere").empty
    assert list_simulations(workspace, limit=1).shape[0] == 1


def test_the_solver_filter_matches_a_run_that_stored_a_solver_list(tmp_path: Path) -> None:
    workspace, project, _sim_id = _seed_workspace(tmp_path)
    seal_run(project, "chain", solver="modflow6,modpath", nse=0.7)
    rebuild_index(project)

    assert set(list_simulations(workspace, solver="modflow6")["name"]) == {"variant", "chain"}


def test_list_simulations_without_an_index_is_empty(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "data").mkdir()

    assert list_simulations(workspace).empty


def test_show_simulation_returns_the_facts(tmp_path: Path) -> None:
    _workspace, project, sim_id = _seed_workspace(tmp_path)

    payload = show_simulation("baseline", workspace=project)

    assert payload["sim_id"] == sim_id
    assert payload["rel_dir"] == "runs/baseline"
    assert payload["label"] == "exploratory"
    assert payload["nse"] == 0.6
    assert payload["exports"] == []


def test_show_simulation_detail_adds_the_zarr_layout(tmp_path: Path) -> None:
    _workspace, project, _sim_id = _seed_workspace(tmp_path)

    payload = show_simulation("variant", workspace=project, detail=True)

    assert "zarr_path" in payload
    assert payload["zarr_exists"] is False


def test_show_simulation_without_an_index_raises(tmp_path: Path) -> None:
    project = make_project(tmp_path / "demo")

    with pytest.raises(FileNotFoundError, match="reindex"):
        show_simulation("baseline", workspace=project)


def test_query_catalog_reads_the_views(tmp_path: Path) -> None:
    _workspace, project, _sim_id = _seed_workspace(tmp_path)

    df = query_catalog("SELECT name, label FROM v_cases ORDER BY name", workspace=project)

    assert df["name"].tolist() == ["baseline", "variant"]
    assert query_catalog("SELECT name FROM simulations", workspace=project, limit=1).shape[0] == 1


def test_query_catalog_invalid_sql_raises_duckdb_error(tmp_path: Path) -> None:
    _workspace, project, _sim_id = _seed_workspace(tmp_path)

    with pytest.raises(duckdb.Error):
        query_catalog("SELECT * FROM no_such_table", workspace=project)


def test_diff_simulations_compares_parameters(tmp_path: Path) -> None:
    _workspace, project, _sim_id = _seed_workspace(tmp_path)

    delta = diff_simulations("baseline", "variant", workspace=project)

    assert ("K", "catchment") in delta["params"]


_AT = datetime(2026, 11, 10, 9, 0, tzinfo=UTC)


def _line(kind, name, seconds, *, attempt=1, reused="no", key=None, rss=None) -> ProfileLine:
    return ProfileLine(
        kind=kind,
        name=name,
        attempt=attempt,
        started_at=_AT,
        duration_s=seconds,
        max_rss_mb=rss,
        reused=reused,
        key=key,
    )


def _write_profile(run_dir: Path, *lines: ProfileLine, ages: dict | None = None) -> None:
    write_profile(run_dir, Profile(lines=lines, process_age_s=ages or {}))


def test_show_simulation_reads_the_profile_from_the_run_folder(tmp_path: Path) -> None:
    _workspace, project, _sim_id = _seed_workspace(tmp_path)
    _write_profile(
        project / "runs" / "baseline",
        _line("step", "build_mesh", 1.5, rss=400.0),
        _line("step", "run_solver", 9.0, rss=900.0),
        _line("solve", "flow_main::modflow6", 8.5),
        _line("step", "extract", 0.5),
        _line("step", "export", 0.25),
        _line("step", "load_data", 0.1, attempt=2, reused="prefix"),
        _line("step", "build_geographic", 2.0, attempt=2, reused="store", key="terrain/ab12"),
        ages={1: 6.4, 2: 5.0},
    )

    profile = show_simulation("baseline", workspace=project)["profile"]

    assert profile["present"] is True
    assert profile["attempts"] == 2
    assert profile["total_s"] == pytest.approx(13.35)
    assert profile["start_s"] == 6.4
    assert profile["max_rss_mb"] == 900.0
    assert profile["solve"] == [{"name": "flow_main::modflow6", "attempt": 1, "duration_s": 8.5}]
    assert [step["name"] for step in profile["longest_steps"]] == [
        "run_solver",
        "build_geographic",
        "build_mesh",
    ]
    assert profile["reused"] == [
        {"name": "load_data", "attempt": 2, "reused": "prefix", "key": None},
        {"name": "build_geographic", "attempt": 2, "reused": "store", "key": "terrain/ab12"},
    ]


def test_a_run_of_the_2_0_release_has_no_profile_and_its_solve_time_is_read_from_the_seal(
    tmp_path: Path,
) -> None:
    _workspace, project, _sim_id = _seed_workspace(tmp_path)
    run_dir = project / "runs" / "variant"
    record = RunRecord.read(run_dir)
    row = MetricRow(
        station="flow_main::modflow6",
        variable="runtime",
        metric=SEALED_SOLVE_METRIC,
        value=26.3,
    )
    record.model_copy(update={"metrics": [*record.metrics, row]}).write(run_dir)

    sealed = show_simulation("variant", workspace=project)["profile"]
    bare = show_simulation("baseline", workspace=project)["profile"]

    assert sealed == {"present": False, "message": NO_PROFILE_TEXT, "solve_s": 26.3}
    assert bare == {"present": False, "message": NO_PROFILE_TEXT, "solve_s": None}
    assert NO_PROFILE_TEXT == "no profile.json, solve time from the seal"


@pytest.mark.parametrize(
    ("lines", "expected"),
    [
        pytest.param((), None, id="profile_without_a_solve_line"),
        pytest.param((_line("solve", "flow", None),), None, id="a_solve_that_did_not_finish"),
        pytest.param((_line("solve", "flow", 3.0),), 3.0, id="one_solve"),
        pytest.param(
            (_line("solve", "flow", 3.0), _line("solve", "transport", 7.0)),
            3.0,
            id="the_flow_comes_first_in_the_plan",
        ),
        pytest.param(
            (
                _line("solve", "flow", 3.0, attempt=1),
                _line("solve", "flow", 4.0, attempt=2),
                _line("solve", "transport", 7.0, attempt=2),
            ),
            4.0,
            id="the_last_attempt_that_solved_gives_the_line",
        ),
        pytest.param(
            (
                _line("solve", "flow", 3.0, attempt=1),
                _line("step", "run_solver", 0.1, attempt=2, reused="prefix"),
            ),
            3.0,
            id="a_resume_past_the_solve_keeps_the_line_of_the_attempt_that_solved",
        ),
    ],
)
def test_the_solve_time_is_the_first_solve_line_of_the_last_attempt_that_solved(
    tmp_path: Path, lines, expected
) -> None:
    _write_profile(tmp_path, *lines)

    assert solve_seconds(tmp_path) == expected


def test_the_solve_time_of_a_folder_without_a_profile_is_none(tmp_path: Path) -> None:
    assert solve_seconds(tmp_path) is None
    assert profile_of_run(tmp_path)["present"] is False
