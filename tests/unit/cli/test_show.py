"""``hmp show``: a session at a glance, a run through ``hmp catalog show``."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hydromodpy.results.session.journal import append_trial
from tests._helpers.sealed_runs import make_project, write_session_dir
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
    assert "report: not written; hmp report render calage writes it" in out


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


def test_a_reference_that_is_no_session_goes_to_catalog_show(monkeypatch, project: Path) -> None:
    seen: dict = {}

    def fake_catalog_show(args) -> None:
        seen.update(ref=args.sim_ref, detail=args.detail)

    monkeypatch.setattr("hydromodpy.cli.commands.catalog.show.run", fake_catalog_show)

    code = run_hmp(monkeypatch, "show", "base.v2", "-w", str(project))

    assert code == 0
    assert seen == {"ref": "base.v2", "detail": False}
