"""``report_run`` and ``report_session``: the text of 4.13 reaches the engine, refusals are named."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from hydromodpy.core.exceptions import ConfigError, DisplayError
from hydromodpy.display.report.presets import SHEET_FIGURES
from hydromodpy.project import report as module
from hydromodpy.project.report import regen_run, report_run, report_session
from hydromodpy.results.storage.contract import RUN_MANIFEST_FILENAME
from tests._helpers.sealed_runs import make_project, write_session_dir

pytestmark = pytest.mark.fast

DAY = date(2026, 11, 11)


def _sealed(project: Path, name: str, site: str = "J0014010") -> Path:
    directory = project / "runs" / name
    directory.mkdir(parents=True)
    (directory / RUN_MANIFEST_FILENAME).write_text("{}", encoding="utf-8")
    return directory


@pytest.fixture
def calls(monkeypatch) -> dict:
    """Replace every reader and writer around the engine by a recorder."""
    seen: dict = {"drawn": [], "opened": []}
    sites: dict[str, str] = {}

    def fake_open(path):
        seen["opened"].append(Path(path))
        return SimpleNamespace(
            name=Path(path).name, site=sites.get(Path(path).name, "J0014010"), dir=path
        )

    def fake_write_pages(out: Path, **options) -> Path:
        seen["write"] = {"out": out, **options}
        out.mkdir(parents=True, exist_ok=True)
        missing = seen.get("missing", [])
        (out / "report.json").write_text(json.dumps({"missing": missing}), encoding="utf-8")
        return out / "index.html"

    def fake_blocks(*_args, **options):
        seen.setdefault("blocks", []).append(options)
        return []

    monkeypatch.setattr(module, "open_run_dir", fake_open)
    monkeypatch.setattr(module, "read_seal", lambda directory: "seal")
    monkeypatch.setattr(
        module, "label_of", lambda seal, directory: SimpleNamespace(label="validated")
    )
    monkeypatch.setattr(
        module, "method_text", lambda directory, lang, today: f"method {lang} {today}"
    )
    monkeypatch.setattr(
        module, "label_text", lambda label, lang, today: f"label {label.label} {lang}"
    )
    monkeypatch.setattr(
        module,
        "draw_report_figures",
        lambda run, stems, station, skipped: seen["drawn"].append((tuple(stems), station)) or (),
    )
    monkeypatch.setattr(module, "run_blocks", fake_blocks)
    monkeypatch.setattr(module, "sheet_blocks", fake_blocks)
    monkeypatch.setattr(module, "write_pages", fake_write_pages)
    seen["sites"] = sites
    return seen


def test_the_management_sheet_is_one_page(calls, tmp_path: Path) -> None:
    run_dir = _sealed(make_project(tmp_path / "p"), "base")

    page = report_run(run_dir, preset="management", today=DAY)

    texts = calls["blocks"][0]["texts"]
    assert texts.titles["method"] == "Method"
    assert texts.method == "method en 2026-11-11"
    assert page == run_dir / "report" / "sheet" / "index.html"
    assert calls["write"]["levels"] is False
    assert calls["drawn"][0][0] == SHEET_FIGURES


def test_the_station_reaches_the_page(calls, tmp_path: Path) -> None:
    run_dir = _sealed(make_project(tmp_path / "p"), "base")

    report_run(run_dir, station="J0014010", today=DAY)

    assert calls["blocks"][0]["station"] == "J0014010"
    assert calls["drawn"][0][1] == "J0014010"


@pytest.mark.parametrize(
    ("case", "message"),
    [
        ("unsealed", "run base is not sealed; a report reads a sealed run"),
        ("other_site", "is the overview of site OTHER"),
        ("unsealed_overview", "overview ov is not sealed"),
        ("preset", "preset 'public' is not one of"),
    ],
)
def test_a_report_refuses_what_it_cannot_read(
    calls, tmp_path: Path, case: str, message: str
) -> None:
    project = make_project(tmp_path / "p")
    options: dict = {"today": DAY}
    if case == "unsealed":
        run_dir = project / "runs" / "base"
        run_dir.mkdir(parents=True)
    else:
        run_dir = _sealed(project, "base")
    if case == "other_site":
        overview = _sealed(project, "ov")
        calls["sites"]["ov"] = "OTHER"
        options["overview_dir"] = overview
    if case == "unsealed_overview":
        (project / "runs" / "ov").mkdir()
        options["overview_dir"] = project / "runs" / "ov"
    if case == "preset":
        options["preset"] = "public"

    with pytest.raises(ConfigError, match=message):
        report_run(run_dir, **options)

    assert "write" not in calls


def test_strict_fails_on_a_missing_required_figure_after_writing(calls, tmp_path: Path) -> None:
    run_dir = _sealed(make_project(tmp_path / "p"), "base")
    calls["missing"] = ["seepage_mask"]

    with pytest.raises(DisplayError, match="seepage_mask"):
        report_run(run_dir, strict=True, today=DAY)

    assert (run_dir / "report" / "report.json").is_file()
    assert report_run(run_dir, strict=False, today=DAY) == run_dir / "report" / "index.html"


def test_a_session_report_never_writes_the_journal(monkeypatch, tmp_path: Path) -> None:
    project = make_project(tmp_path / "p")
    write_session_dir(project, "calage", trials=2)
    directory = project / "sessions" / "calage"
    written: dict = {}
    monkeypatch.setattr(module, "SESSION_FIGURES", ("calibration_progress", "nope"))

    def fake_write_pages(out: Path, **options) -> Path:
        written.update(out=out, **options)
        return out / "index.html"

    monkeypatch.setattr(module, "write_pages", fake_write_pages)
    monkeypatch.setattr(module, "session_blocks", lambda *a, **k: [])
    _fake_drawing(monkeypatch)
    before = {path.name: path.stat().st_mtime_ns for path in directory.iterdir()}

    page = report_session(directory, today=DAY)

    assert page == directory / "report" / "index.html"
    assert (directory / "figures" / "calibration_progress.png").is_file()
    assert not (directory / "figures" / "nope.png").exists()
    for name, stamp in before.items():
        assert (directory / name).stat().st_mtime_ns == stamp, f"{name} was written"
    assert not (directory / "trial_series").exists()
    assert written["preset"] == "research"


def _fake_drawing(monkeypatch) -> None:
    """Draw nothing and write a stub PNG where ``output.write`` would."""

    def write(fig, figure, run, directory: Path, theme) -> list[Path]:
        path = directory / f"{figure.stem}.png"
        path.write_bytes(b"png")
        return [path]

    monkeypatch.setattr(module, "render", lambda *args, **kwargs: None)
    monkeypatch.setattr(module, "write", write)


def test_a_best_run_that_does_not_open_leaves_the_page_without_its_figures(
    monkeypatch, tmp_path: Path
) -> None:
    from hydromodpy.results.session.view import Session

    project = make_project(tmp_path / "p")
    write_session_dir(project, "calage", trials=2)
    directory = project / "sessions" / "calage"

    def refuse(self):
        raise OSError("manifest.json is unreadable")

    monkeypatch.setattr(Session, "best_by_case", property(refuse))
    monkeypatch.setattr(module, "SESSION_FIGURES", ())
    page = report_session(directory, today=DAY)

    text = page.read_text(encoding="utf-8")
    assert "best run not opened: manifest.json is unreadable" in text
    assert "Iteration trace" in text


def test_a_session_of_several_cases_draws_the_best_run_of_each(monkeypatch, tmp_path: Path) -> None:
    from hydromodpy.results.session.view import Session

    project = make_project(tmp_path / "p")
    write_session_dir(project, "calage", trials=2)
    directory = project / "sessions" / "calage"
    runs = {"a": SimpleNamespace(name="a.v1"), "b": SimpleNamespace(name="b.v1")}
    monkeypatch.setattr(Session, "best_by_case", property(lambda self: runs))
    monkeypatch.setattr(
        Session,
        "descriptor",
        property(
            lambda self: SimpleNamespace(
                cases={"a": SimpleNamespace(site="A"), "b": SimpleNamespace(site="B")},
                session_id="s",
            )
        ),
    )
    seen: dict = {}

    def spy_blocks(session, **options):
        seen.update(options)
        return []

    monkeypatch.setattr(module, "SESSION_FIGURES", ())
    monkeypatch.setattr(
        module, "session_summary", lambda session: SimpleNamespace(calibrated_variable="discharge")
    )
    monkeypatch.setattr(module, "summary_rows", lambda summary: [])
    monkeypatch.setattr(module, "session_blocks", spy_blocks)
    _fake_drawing(monkeypatch)

    report_session(directory, today=DAY)

    assert [row["best_run"] for row in seen["cases"]] == ["a.v1", "b.v1"]
    assert sorted(p.name for p in seen["best_figures"]) == [
        "a_hydrograph.png",
        "a_scatter_one_to_one.png",
        "b_hydrograph.png",
        "b_scatter_one_to_one.png",
    ]


def test_regen_writes_again_the_export_the_ledger_records(tmp_path: Path) -> None:
    from hydromodpy.project.api import export
    from tests._helpers.run_stores import RUN_NAME, seal_demo_run

    project = tmp_path / "project"
    seal_demo_run(project)
    export(RUN_NAME, "head", time="last", workspace=project)
    written = project / "runs" / RUN_NAME / "exports" / "head_last.tif"
    written.unlink()

    assert regen_run(RUN_NAME, workspace=project) == [written]
    assert written.is_file()


def test_regen_of_a_run_that_records_nothing_is_refused_for_all(tmp_path: Path) -> None:
    from hydromodpy.core.exceptions import ResultsError
    from tests._helpers.run_stores import RUN_NAME, seal_demo_run

    project = tmp_path / "project"
    seal_demo_run(project)

    with pytest.raises(ResultsError, match="records no export and no figure"):
        regen_run(RUN_NAME, workspace=project)
