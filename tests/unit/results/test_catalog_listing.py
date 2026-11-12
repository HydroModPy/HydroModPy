"""The listing functions of ``hmp catalog`` answer from the index of an indexed project."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import duckdb
import pytest

from hydromodpy.core.state.layout import PROJECTS_DIRNAME, WORKSPACE_TOML_FILENAME
from hydromodpy.results.catalog.indexer import rebuild_index
from hydromodpy.results.catalog.listing import (
    list_runs,
    list_simulations,
    profile_of_run,
    query_catalog,
    show_simulation,
    simulation_facts,
    solve_seconds,
)
from hydromodpy.results.publication import PublishedLine, append_published
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


def test_show_simulation_lists_the_latest_delivery_of_each_pair(tmp_path: Path) -> None:
    _workspace, project, _sim_id = _seed_workspace(tmp_path)
    run_dir = project / "runs" / "baseline"
    for state, attempts in (("pending", 0), ("delivered", 1)):
        append_published(
            run_dir,
            PublishedLine(
                kind="delivery",
                file="exports/head_last.tif",
                destination="/data/depot/head_last.tif",
                state=state,
                sha256="a" * 64,
                bytes=3,
                attempts=attempts,
                published_at=datetime(2026, 11, 10, tzinfo=UTC),
            ),
        )

    payload = show_simulation("baseline", workspace=project)

    assert [(entry["state"], entry["attempts"]) for entry in payload["deliveries"]] == [
        ("delivered", 1)
    ]
    assert payload["deliveries"][0]["file"] == "exports/head_last.tif"


def test_show_simulation_detail_adds_the_zarr_layout(tmp_path: Path) -> None:
    _workspace, project, _sim_id = _seed_workspace(tmp_path)

    payload = show_simulation("variant", workspace=project, detail=True)

    assert "zarr_path" in payload
    assert payload["zarr_exists"] is False


def test_show_simulation_lists_the_latest_copy_of_each_destination(tmp_path: Path) -> None:
    _workspace, project, _sim_id = _seed_workspace(tmp_path)
    run_dir = project / "runs" / "baseline"
    for day, to in ((9, "/data/a"), (10, "/data/b"), (11, "/data/a")):
        append_published(
            run_dir,
            PublishedLine(
                kind="copy",
                to=to,
                format="dir",
                publication_sha256="b" * 64,
                published_at=datetime(2026, 11, day, tzinfo=UTC),
            ),
        )

    payload = show_simulation("baseline", workspace=project)

    assert [(entry["to"], entry["published_at"][:10]) for entry in payload["copies"]] == [
        ("/data/a", "2026-11-11"),
        ("/data/b", "2026-11-10"),
    ]


def test_opening_a_project_without_an_index_builds_it(tmp_path: Path) -> None:
    project = make_project(tmp_path / "demo")
    seal_run(project, "baseline")
    assert not (project / ".hmp" / "index.duckdb").exists()

    payload = show_simulation("baseline", workspace=project)

    assert payload["rel_dir"] == "runs/baseline"
    assert (project / ".hmp" / "index.duckdb").is_file()


def test_query_catalog_reads_the_views(tmp_path: Path) -> None:
    _workspace, project, _sim_id = _seed_workspace(tmp_path)

    df = query_catalog("SELECT name, label FROM v_cases ORDER BY name", workspace=project)

    assert df["name"].tolist() == ["baseline", "variant"]
    assert query_catalog("SELECT name FROM simulations", workspace=project, limit=1).shape[0] == 1


def test_query_catalog_invalid_sql_raises_duckdb_error(tmp_path: Path) -> None:
    _workspace, project, _sim_id = _seed_workspace(tmp_path)

    with pytest.raises(duckdb.Error):
        query_catalog("SELECT * FROM no_such_table", workspace=project)


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


def test_the_facts_of_a_run_hold_its_tags_notes_metrics_and_parameters(tmp_path: Path) -> None:
    from hydromodpy.results.annotations import add_note
    from hydromodpy.results.catalog.facade import Catalog

    _workspace, project, sim_id = _seed_workspace(tmp_path)
    add_note(project / "runs" / "baseline", "first")
    add_note(project / "runs" / "baseline", "second")
    rebuild_index(project)

    with Catalog(project) as catalog:
        facts = simulation_facts(catalog, sim_id)
        bare = simulation_facts(catalog, catalog.resolve("variant"))

    assert facts.tags == ["pinned"]
    assert facts.notes == ["first", "second"]
    assert not facts.metrics.empty
    assert bare.tags == [] and bare.notes == []
    assert "K" in set(bare.parameters.reset_index().astype(str).to_numpy().ravel())


def test_no_run_gives_an_empty_frame_and_no_reason(tmp_path: Path) -> None:
    workspace, _project, _sim_id = _seed_workspace(tmp_path)

    frame, reasons = list_runs(workspace, site="nowhere", best="nse")

    assert frame.empty
    assert reasons == []


def test_limit_counts_the_ranked_rows_when_best_is_asked(tmp_path: Path) -> None:
    workspace, _project, _sim_id = _seed_workspace(tmp_path)

    unranked, _ = list_runs(workspace, limit=1)
    ranked, reasons = list_runs(workspace, best="nse", limit=1)

    assert len(unranked) == 1
    assert len(ranked) <= 1
    assert isinstance(reasons, list)


def test_an_unknown_metric_is_refused_by_name(tmp_path: Path) -> None:
    from hydromodpy.results.catalog.constants import UnrankedMetricError

    workspace, _project, _sim_id = _seed_workspace(tmp_path)

    with pytest.raises(UnrankedMetricError):
        list_runs(workspace, best="no_such_metric")
