"""``hmp diff``: what differs between two runs, or a folder with the whole comparison."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hydromodpy.project.compare import ComparisonCaseError, ComparisonReferenceError
from hydromodpy.results.catalog.indexer import rebuild_index
from tests._helpers.sealed_runs import make_project, seal_run

from ._hmp import run_hmp

pytestmark = pytest.mark.fast


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = make_project(tmp_path / "demo")
    seal_run(root, "alpha")
    seal_run(root, "beta")
    rebuild_index(root)
    return root


@pytest.fixture
def compared(monkeypatch) -> dict:
    """Replace the verb by a function that records its call and writes nothing."""
    seen: dict = {}

    def verb(refs, **kwargs):
        seen.update(kwargs, refs=list(refs))
        return Path(kwargs["out"])

    monkeypatch.setattr("hydromodpy.project.api.compare", verb)
    return seen


def test_two_runs_print_what_differs_in_params_and_metrics(
    monkeypatch, capsys, project: Path
) -> None:
    code = run_hmp(monkeypatch, "diff", "alpha", "beta", "-w", str(project))

    out = capsys.readouterr().out
    assert code == 0
    assert out.splitlines()[0].startswith("a: ")
    assert "params" in out and "metrics" in out


def test_two_runs_in_json_keep_the_shape_of_the_old_diff(
    monkeypatch, capsys, project: Path
) -> None:
    code = run_hmp(monkeypatch, "diff", "alpha", "beta", "-w", str(project), "--format", "json")

    document = json.loads(capsys.readouterr().out)
    assert code == 0
    assert document["schema"] == "hmp.diff.v1"
    assert set(document["data"]) == {"a", "b", "params", "metrics"}


def test_to_writes_the_comparison_folder_through_the_verb(
    monkeypatch, capsys, project: Path, compared: dict, tmp_path: Path
) -> None:
    folder = tmp_path / "study"

    code = run_hmp(monkeypatch, "diff", "alpha", "beta", "--to", str(folder), "-w", str(project))

    assert code == 0
    assert compared["refs"] == ["alpha", "beta"]
    assert compared["out"] == folder
    assert compared["by"] == "run"
    assert Path(compared["workspace"]) == project
    assert f"wrote {folder}" in capsys.readouterr().err


def test_without_to_the_folder_is_under_the_summary_of_the_project(
    monkeypatch, project: Path, compared: dict
) -> None:
    code = run_hmp(monkeypatch, "diff", "alpha", "beta", "gamma", "-w", str(project))

    assert code == 0
    expected = project / "summary" / "report" / "compare" / "alpha-vs-beta-vs-gamma"
    assert compared["out"] == expected


def test_by_site_and_variables_reach_the_verb(monkeypatch, project: Path, compared: dict) -> None:
    code = run_hmp(
        monkeypatch,
        *("diff", "alpha", "beta", "--by", "site", "--variables", "head, discharge"),
        *("-w", str(project)),
    )

    assert code == 0
    assert compared["by"] == "site"
    assert compared["variables"] == ["head", "discharge"]


@pytest.mark.parametrize(
    ("error", "code"),
    [(ComparisonReferenceError("no run gamma"), 10), (ComparisonCaseError("two sites"), 16)],
)
def test_a_refused_comparison_exits_with_its_category(
    monkeypatch, capsys, project: Path, error: Exception, code: int
) -> None:
    def verb(refs, **kwargs):
        raise error

    monkeypatch.setattr("hydromodpy.project.api.compare", verb)

    assert run_hmp(monkeypatch, "diff", "alpha", "beta", "--to", "out", "-w", str(project)) == code
    assert str(error) in capsys.readouterr().err


def test_the_old_forms_are_refused_with_the_new_one(monkeypatch, capsys, project: Path) -> None:
    assert run_hmp(monkeypatch, "catalog", "diff", "alpha", "beta") == 2
    assert "Write: hmp diff REF REF" in capsys.readouterr().err
    assert run_hmp(monkeypatch, "report", "compare", "alpha", "beta", "--out", "x") == 2
    assert "Write: hmp diff REF REF --to DIR" in capsys.readouterr().err


def _seal_record(project: Path, name: str, *, site: str) -> None:
    """Write one sealed run record of *site*, enough to resolve and to refuse."""
    from tests._helpers.run_records import make_identity, make_record

    base = make_record()
    run_dir = project / "runs" / name
    run_dir.mkdir(parents=True)
    make_record(
        run=base.run.model_copy(
            update={"name": name, "case_id": f"{site}-r", "rel_dir": f"runs/{name}"}
        ),
        site=base.site.model_copy(update={"name": site, "fingerprint": f"fp_{site}"}),
        identity=make_identity(site=site, site_fingerprint=f"fp_{site}", case_id=f"{site}-r"),
    ).write(run_dir)


def test_the_command_gives_typed_exit_codes(tmp_path: Path, monkeypatch) -> None:
    from hydromodpy.cli.exit_codes import EXIT_NOT_FOUND, EXIT_VALIDATION
    from hydromodpy.cli.main import main as hmp_main

    project = tmp_path / "bretagne"
    project.mkdir()
    (project / "project.toml").write_text("", encoding="utf-8")
    _seal_record(project, "one", site="s1")
    _seal_record(project, "two", site="s2")
    monkeypatch.chdir(project)
    for refs, code in ((["one", "nowhere"], EXIT_NOT_FOUND), (["one", "two"], EXIT_VALIDATION)):
        with pytest.raises(SystemExit) as refused:
            hmp_main(["diff", *refs, "--to", str(project / "out")])
        assert refused.value.code == code


def test_the_command_writes_in_the_project_or_where_it_is_told(project: Path, monkeypatch) -> None:
    from types import SimpleNamespace

    from hydromodpy.cli.main import main as hmp_main
    from hydromodpy.project import compare as c

    written: list[Path] = []
    comparison = SimpleNamespace(
        write=lambda folder: written.append(Path(folder)) or Path(folder) / "README.md"
    )
    monkeypatch.setattr(c, "compare_references", lambda refs, **_: comparison)
    monkeypatch.setattr(
        c, "compare_by_site", lambda refs, folder, **_: written.append(Path(folder))
    )
    monkeypatch.chdir(project)
    hmp_main(["diff", "runs/a", "b c", "--variables", "head, ,x"])
    hmp_main(["diff", "a", "b", "--by", "site", "--to", "elsewhere"])
    assert written == [project / "summary/report/compare/a-vs-b_c", Path("elsewhere")]
