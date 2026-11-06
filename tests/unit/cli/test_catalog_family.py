"""Tests for the ``hmp catalog`` family (ls, query, show, gc, delete)."""

from __future__ import annotations

import hashlib
import importlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from hydromodpy.calibration.criteria.series import HIGHER_IS_BETTER, METRICS
from hydromodpy.core.state.layout import catalog_path_for
from hydromodpy.results.annotations import add_note, add_tag, read_annotations
from hydromodpy.results.catalog import Catalog, rebuild_index
from hydromodpy.results.catalog.constants import METRIC_SENSE
from hydromodpy.results.storage.sealing import seal_completed
from tests._helpers.cli_runner import CliRunner
from tests._helpers.metric_rows import headline_row
from tests._helpers.run_stores import open_run_store
from tests._helpers.sealed_runs import SITE, make_project, manifest_document, seal_run

from ._hmp import run_hmp as _hmp
from ._hmp import run_main as _run


def _make_workspace_with_catalog(tmp_path: Path) -> Path:
    from hydromodpy.results.catalog import rebuild_index
    from tests._helpers.sealed_runs import make_project, seal_run

    workspace = tmp_path / "ws"
    workspace.mkdir()
    project = make_project(workspace / "projects" / "demo")
    (workspace / "data").mkdir()
    seal_run(project, "alpha")
    rebuild_index(project)
    return workspace


def test_catalog_family_help_lists_actions(monkeypatch, capsys) -> None:
    code = _run(monkeypatch, ["hmp", "catalog", "--help"])
    assert code == 0
    out = capsys.readouterr().out
    for action in ("ls", "query", "show", "gc", "delete"):
        assert action in out


def test_catalog_ls_empty_workspace(monkeypatch, tmp_path, capsys) -> None:
    workspace = _make_workspace_with_catalog(tmp_path)
    code = _run(monkeypatch, ["hmp", "catalog", "ls", "--workspace", str(workspace)])
    assert code == 0


def test_catalog_query_missing_workspace_returns_not_found(monkeypatch, tmp_path) -> None:
    missing = tmp_path / "empty_ws"
    missing.mkdir()
    code = _run(
        monkeypatch,
        ["hmp", "catalog", "query", "SELECT 1", "--workspace", str(missing)],
    )
    assert code == 10


def test_catalog_query_runs_on_existing_catalog(monkeypatch, tmp_path, capsys) -> None:
    workspace = _make_workspace_with_catalog(tmp_path)
    project = workspace / "projects" / "demo"
    code = _run(
        monkeypatch,
        ["hmp", "catalog", "query", "SELECT 1 AS one", "--workspace", str(project)],
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "one" in out


def test_catalog_show_unknown_sim_returns_not_found(monkeypatch, tmp_path) -> None:
    workspace = _make_workspace_with_catalog(tmp_path)
    project = workspace / "projects" / "demo"
    code = _run(
        monkeypatch,
        ["hmp", "catalog", "show", "deadbeef", "--workspace", str(project)],
    )
    assert code == 10


README = "# alpha\n\nRun `alpha` of project `demo`, status **completed**.\n"


def test_show_prints_the_readme_and_the_annotations(monkeypatch, capsys, tmp_path) -> None:
    project = make_project(tmp_path / "demo")
    run_dir = project / "runs" / "alpha"
    seal_run(project, "alpha")
    (run_dir / "README.md").write_text(README, encoding="utf-8")
    add_tag(run_dir, "pinned")
    add_note(run_dir, "K hits its upper bound", now=datetime(2026, 10, 16, 8, 0, tzinfo=UTC))

    code = _run(monkeypatch, ["hmp", "catalog", "show", "alpha", "-w", str(project)])

    assert code == 0
    out = capsys.readouterr().out
    assert out.startswith(README.rstrip())
    assert "tags: pinned" in out
    assert "2026-10-16 08:00 K hits its upper bound" in out
    assert "hmp catalog show runs/alpha --detail" in out
    assert not catalog_path_for(project).exists(), "show never builds the index"


def test_show_of_a_name_the_project_lacks_exits_not_found(monkeypatch, capsys, tmp_path) -> None:
    project = make_project(tmp_path / "demo")
    seal_run(project, "alpha")

    code = _run(monkeypatch, ["hmp", "catalog", "show", "beta", "-w", str(project)])

    assert code == 10
    assert "beta" in capsys.readouterr().err


def test_show_of_last_outside_a_workspace_names_dash_w(monkeypatch, capsys, tmp_path) -> None:
    monkeypatch.chdir(make_project(tmp_path / "demo"))

    code = _run(monkeypatch, ["hmp", "catalog", "show", "@last"])

    assert code == 10
    err = capsys.readouterr().err
    assert "'@last' is answered by the index" in err
    assert "with -w" in err


def test_show_of_last_with_dash_w_does_not_repeat_the_hint(monkeypatch, capsys, tmp_path) -> None:
    project = make_project(tmp_path / "demo")

    code = _run(monkeypatch, ["hmp", "catalog", "show", "@last", "-w", str(project)])

    assert code == 10
    assert "with -w" not in capsys.readouterr().err


SIM_ID = "9a4f0c1e-0000-4000-8000-000000000001"


def _calibration_run(tmp_path: Path) -> tuple[Path, Path]:
    project = tmp_path / "p"
    run_dir = project / "runs" / "calibration"
    run_dir.mkdir(parents=True)
    (project / "project.toml").write_text('[site]\nname = "p"\n', encoding="utf-8")
    (run_dir / "manifest.json").write_text(
        json.dumps(manifest_document(sim_id=SIM_ID)),
        encoding="utf-8",
    )
    return project, run_dir


def test_tags_are_added_once_and_removed(tmp_path: Path, monkeypatch) -> None:
    project, run_dir = _calibration_run(tmp_path)
    w = ("-w", str(project))
    assert _hmp(monkeypatch, "catalog", "tag", "calibration", "pinned", "paper", *w) == 0
    assert _hmp(monkeypatch, "catalog", "tag", "calibration", "+paper", *w) == 0
    assert read_annotations(run_dir).tags == ("pinned", "paper")
    assert _hmp(monkeypatch, "catalog", "tag", "calibration", "--rm", "paper", *w) == 0
    assert read_annotations(run_dir).tags == ("pinned",)
    payload = json.loads((run_dir / "annotations.json").read_text(encoding="utf-8"))
    assert payload["sim_id"] == SIM_ID


def test_a_note_is_appended_with_its_instant(tmp_path: Path, monkeypatch) -> None:
    project, run_dir = _calibration_run(tmp_path)
    w = ("-w", str(project))
    assert _hmp(monkeypatch, "catalog", "note", "runs/calibration", "best fit", *w) == 0
    assert _hmp(monkeypatch, "catalog", "note", "calibration", "kept for the paper", *w) == 0
    notes = read_annotations(run_dir).notes
    assert [note.text for note in notes] == ["best fit", "kept for the paper"]
    assert all(note.at for note in notes)
    assert not (project / ".hmp").exists()


def test_an_indexed_run_keeps_its_row_and_note_after_a_note(tmp_path: Path, monkeypatch) -> None:
    import duckdb

    from hydromodpy.core.state.layout import catalog_path_for
    from tests._helpers.sealed_runs import make_project, seal_run

    project = make_project(tmp_path / "p")
    seal_run(project, "first")
    rebuild_index(project)
    w = ("-w", str(project))
    assert _hmp(monkeypatch, "catalog", "note", "first", "a note", *w) == 0
    conn = duckdb.connect(str(catalog_path_for(project)), read_only=True)
    try:
        rel_dirs = [row[0] for row in conn.execute("SELECT rel_dir FROM simulations").fetchall()]
        notes = [row[0] for row in conn.execute("SELECT note FROM sim_notes").fetchall()]
    finally:
        conn.close()
    assert rel_dirs == ["runs/first"]
    assert notes == ["a note"]


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def project(tmp_path) -> Path:
    root = make_project(tmp_path / "demo")
    seal_run(root, "alpha", mesh_engine=None)
    seal_run(root, "voronoi_run", mesh_engine="voronoi", config_text='[mesh]\nengine = "voronoi"\n')
    rebuild_index(root)
    return root


@pytest.mark.parametrize(
    "argv",
    [
        ["hmp", "catalog", "ls"],
        ["hmp", "catalog", "show", "alpha"],
        ["hmp", "catalog", "query", "SELECT COUNT(*) FROM simulations"],
    ],
)
def test_inspecting_leaves_the_index_byte_for_byte(monkeypatch, project, argv) -> None:
    index = catalog_path_for(project)
    before = _digest(index)
    mtime = index.stat().st_mtime_ns

    assert _run(monkeypatch, [*argv, "--workspace", str(project)]) == 0

    assert _digest(index) == before
    assert index.stat().st_mtime_ns == mtime


def test_a_reader_refuses_to_write(project) -> None:
    with Catalog(project) as catalog:
        with pytest.raises(Exception, match="read-only|Cannot execute|read_only"):
            catalog.backend.execute("DELETE FROM simulations")


def test_a_reader_never_creates_an_index(tmp_path) -> None:
    empty = make_project(tmp_path / "empty")

    with pytest.raises(FileNotFoundError, match="reindex"):
        Catalog(empty)
    assert not catalog_path_for(empty).exists()


def test_ls_shows_a_dash_for_a_run_with_no_mesh_engine(monkeypatch, project, capsys) -> None:
    assert _run(monkeypatch, ["hmp", "catalog", "ls", "--workspace", str(project)]) == 0
    lines = [line for line in capsys.readouterr().out.splitlines() if "alpha" in line]
    assert len(lines) == 1
    assert "mesh=-" in lines[0]


def test_ls_shows_the_mesh_engine_of_a_run(monkeypatch, project, capsys) -> None:
    assert _run(monkeypatch, ["hmp", "catalog", "ls", "--workspace", str(project)]) == 0
    lines = [line for line in capsys.readouterr().out.splitlines() if "voronoi_run" in line]
    assert len(lines) == 1
    assert "mesh=voronoi" in lines[0]


@pytest.fixture
def workspace(tmp_path):
    """Three completed runs a, b, c of project p, scored on nse, rmse and pbias."""
    scores = {
        "a": {"nse": 0.6, "rmse": 2.0, "pbias": -20.0},
        "b": {"nse": 0.9, "rmse": 0.5, "pbias": 5.0},
        "c": {"nse": 0.3, "rmse": 3.0, "pbias": 30.0},
    }
    root = tmp_path / "p"
    for name, metrics in scores.items():
        store = open_run_store(root, name, create_zarr=False)
        for metric, value in {**metrics, "unknown_score": 1.0}.items():
            store.write_metric(
                store.sim_id, headline_row(metric, value, station=SITE, variable="head")
            )
        seal_completed(store)
    rebuild_index(root)
    return root


def _names(stdout: str) -> list[str]:
    return [line.split()[1] for line in stdout.splitlines() if "#" in line.split()[0]]


@pytest.mark.parametrize(
    ("metric", "best_first", "worst_first"),
    [
        ("nse", ["b", "a", "c"], ["c", "a", "b"]),
        ("rmse", ["b", "a", "c"], ["c", "a", "b"]),
        ("pbias", ["b", "a", "c"], ["c", "a", "b"]),
    ],
)
def test_top_and_bottom_follow_the_metric(workspace, metric, best_first, worst_first) -> None:
    common = [
        "catalog",
        "rank",
        "--project",
        "p",
        "--metric",
        metric,
        "--workspace",
        str(workspace),
    ]

    top = CliRunner().invoke([*common, "--top", "3"])
    bottom = CliRunner().invoke([*common, "--bottom", "3"])

    assert top.exit_code == 0, top.stderr
    assert _names(top.stdout) == best_first
    assert bottom.exit_code == 0, bottom.stderr
    assert _names(bottom.stdout) == worst_first


def test_a_metric_without_direction_is_refused(workspace) -> None:
    result = CliRunner().invoke(
        [
            "catalog",
            "rank",
            "--project",
            "p",
            "--metric",
            "unknown_score",
            "--workspace",
            str(workspace),
        ]
    )

    assert result.exit_code == 10
    assert "no declared direction" in result.stderr


def test_every_calibration_metric_has_a_direction() -> None:
    """A criterion turns a score into a cost: its metric is either max or min."""
    for name in METRICS:
        assert METRIC_SENSE.get(name) in {"max", "min"}, name
    assert {name for name in METRICS if METRIC_SENSE[name] == "max"} == HIGHER_IS_BETTER
