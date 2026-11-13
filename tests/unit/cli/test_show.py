"""``hmp show``: a session at a glance, a run, a table, a figure, and the selectors that read the rest."""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.results.session.journal import append_trial
from tests._helpers.cli_runner import CliRunner
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


def test_the_profile_alone_is_the_profile_of_the_run(monkeypatch, capsys, tmp_path: Path) -> None:
    root = make_project(tmp_path / "demo")
    seal_run(root, "alpha")

    code = run_hmp(monkeypatch, "show", "alpha", "--profile", "-w", str(root))

    out = capsys.readouterr().out
    assert code == 0
    assert out.lstrip().startswith("Profile")
    assert "# alpha" not in out


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


def _png(path: Path) -> Path:
    from PIL import Image

    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (4, 4), "white").save(path)
    return path


@pytest.fixture
def figure_project(tmp_path: Path) -> Path:
    root = make_project(tmp_path / "demo")
    seal_run(root, "alpha")
    return root


def test_figure_reaches_the_verb(monkeypatch, figure_project: Path) -> None:
    seen: dict[str, object] = {}

    def verb(ref, **kwargs):
        seen.update(kwargs, ref=ref)
        return _png(Path(kwargs["save"]) / "head.png")

    monkeypatch.setattr("hydromodpy.project.api.show", verb)

    result = CliRunner().invoke(
        [
            "show",
            "alpha",
            "--figure",
            "head",
            "--time",
            "2002-10-15",
            "-w",
            str(figure_project),
        ]
    )

    assert result.exit_code == 0, result.stderr
    assert seen["what"] == "figure"
    assert seen["name"] == "head"
    assert seen["options"] == {"time": "2002-10-15"}
    assert Path(seen["save"]) == figure_project / "runs" / "alpha" / "figures"


def test_figure_refuses_the_project(figure_project: Path) -> None:
    result = CliRunner().invoke(["show", "--figure", "head_map", "-w", str(figure_project)])

    assert result.exit_code == 2
    assert "draws a run or a session" in result.stderr
