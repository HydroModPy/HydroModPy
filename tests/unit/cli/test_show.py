"""``hmp show``: a session at a glance, a run, a project, and the selectors that read the rest."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hydromodpy.results.catalog.indexer import rebuild_index
from hydromodpy.results.session.journal import append_trial
from tests._helpers.sealed_runs import make_project, seal_run, write_session_dir
from tests._helpers.session_documents import trial_line

from ._hmp import run_hmp

pytestmark = pytest.mark.fast


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = make_project(tmp_path / "p")
    write_session_dir(root, "calage", trials=0, best_trial=2)
    directory = root / "sessions" / "calage"
    append_trial(directory, trial_line(1, case="calage", phase="steady_k", status="failed"))
    bounded = {"value": 1e-7, "bounds": (1e-7, 1e-4)}
    append_trial(directory, trial_line(2, case="calage", phase="steady_k", params={"K": bounded}))
    return root


@pytest.mark.parametrize("reference", ["calage", "sessions/calage"])
def test_a_session_prints_its_rows_and_where_the_report_goes(
    monkeypatch, capsys, project: Path, reference: str
) -> None:
    code = run_hmp(monkeypatch, "show", reference, "-w", str(project))

    assert code == 0
    out = capsys.readouterr().out
    assert "trials" in out
    assert "1 completed, 1 failed" in out
    assert "bounds reached      : K" in out
    assert "report: not written; hmp show calage --report writes it" in out


def test_a_written_report_is_named(monkeypatch, capsys, project: Path) -> None:
    page = project / "sessions" / "calage" / "report" / "index.html"
    page.parent.mkdir()
    page.write_text("<html></html>", encoding="utf-8")

    run_hmp(monkeypatch, "show", "calage", "-w", str(project))

    assert f"report: {page}" in capsys.readouterr().out


def test_a_session_in_json_carries_the_summary(monkeypatch, capsys, project: Path) -> None:
    code = run_hmp(monkeypatch, "show", "calage", "-w", str(project), "--format", "json")

    document = json.loads(capsys.readouterr().out)
    assert code == 0
    assert document["schema"] == "hmp.show.v1"
    data = document["data"]
    assert data["name"] == "calage"
    assert data["trials_by_status"] == {"completed": 1, "failed": 1}
    assert data["best_trial"] == 2
    assert data["bounds_reached"] == ["K"]
    assert data["report"] is None


def test_a_run_prints_its_readme_and_its_profile(monkeypatch, capsys, tmp_path: Path) -> None:
    root = make_project(tmp_path / "demo")
    seal_run(root, "alpha")
    (root / "runs" / "alpha" / "README.md").write_text("# alpha\n", encoding="utf-8")

    code = run_hmp(monkeypatch, "show", "alpha", "-w", str(root))

    out = capsys.readouterr().out
    assert code == 0
    assert out.startswith("# alpha")
    assert "Profile" in out
    assert "next: hmp show alpha --detail | hmp diff alpha <other>" in out


def test_the_profile_alone_is_the_profile_of_the_run(monkeypatch, capsys, tmp_path: Path) -> None:
    root = make_project(tmp_path / "demo")
    seal_run(root, "alpha")

    code = run_hmp(monkeypatch, "show", "alpha", "--profile", "-w", str(root))

    out = capsys.readouterr().out
    assert code == 0
    assert out.lstrip().startswith("Profile")
    assert "# alpha" not in out


def test_a_run_in_json_names_its_facts(monkeypatch, capsys, tmp_path: Path) -> None:
    root = make_project(tmp_path / "demo")
    seal_run(root, "alpha")
    rebuild_index(root)

    code = run_hmp(monkeypatch, "show", "alpha", "-w", str(root), "--format", "json")

    document = json.loads(capsys.readouterr().out)
    assert code == 0
    assert document["schema"] == "hmp.show.run.v1"
    assert document["data"]["name"] == "alpha"
    assert document["data"]["rel_dir"] == "runs/alpha"


def test_the_project_is_what_show_reads_without_a_reference(
    monkeypatch, capsys, project: Path
) -> None:
    code = run_hmp(monkeypatch, "show", "-w", str(project), "--format", "json")

    document = json.loads(capsys.readouterr().out)
    assert code == 0
    assert document["schema"] == "hmp.show.project.v1"
    assert document["data"]["n_sessions"] == 1


def test_a_table_is_what_the_verb_reads_and_written_where_to_says(
    monkeypatch, capsys, project: Path, tmp_path: Path
) -> None:
    import pandas as pd

    seen: dict = {}

    def verb(ref, **kwargs):
        seen.update(kwargs)
        return pd.DataFrame({"trial": [1, 2], "cost": [0.5, 0.25]})

    monkeypatch.setattr("hydromodpy.project.api.show", verb)
    target = tmp_path / "trials.csv"

    code = run_hmp(
        monkeypatch, "show", "calage", "--table", "trials", "--to", str(target), "-w", str(project)
    )

    assert code == 0
    assert seen["what"] == "table" and seen["name"] == "trials"
    assert pd.read_csv(target)["cost"].tolist() == [0.5, 0.25]
    assert f"written: {target}" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("argv", "says"),
    [
        (["show", "calage", "--figure", "x", "--point"], "not allowed with argument"),
        (["show", "a", "b"], "only --point reads several runs"),
        (["show", "calage", "--to", "out.json"], "--to writes a figure"),
        (["show", "a", "--point"], "--point needs --var NAME"),
        (["show", "a", "--point", "--var", "head"], "--point needs the cell"),
        (["show", "--point", "--var", "head", "--cell", "1"], "--point reads runs"),
        (["show", "--profile"], "reads a run or a session"),
        (["show", "--rank", "nse", "calage"], "--rank reads the project"),
    ],
)
def test_a_selector_the_subject_cannot_hold_is_a_usage_error(
    monkeypatch, capsys, project: Path, argv: list[str], says: str
) -> None:
    code = run_hmp(monkeypatch, *argv, "-w", str(project))

    assert code == 2
    assert says in capsys.readouterr().err


def test_an_unknown_reference_exits_not_found_and_names_dash_w(
    monkeypatch, capsys, tmp_path: Path
) -> None:
    root = make_project(tmp_path / "demo")
    seal_run(root, "alpha")
    monkeypatch.chdir(tmp_path)

    code = run_hmp(monkeypatch, "show", "beta")

    assert code == 10
    assert "Name the workspace or the project with -w." in capsys.readouterr().err
