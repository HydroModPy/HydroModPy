"""Tests for the ``hmp report catchment`` command wiring: it reads a sealed run."""

from __future__ import annotations

import importlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from hydromodpy.cli.commands.report import REFUSED_REPORT_FILE, REPORT_PRESETS
from hydromodpy.cli.helpers import EXIT_CONFIG, EXIT_USAGE
from hydromodpy.display.report.presets import PRESETS

pytestmark = pytest.mark.fast


def _main(argv: list[str]) -> None:
    importlib.import_module("hydromodpy.cli.main").main(argv)


@pytest.fixture
def written(monkeypatch, tmp_path: Path) -> dict:
    """Replace ``report_run`` by a function that records its call and writes a report.json."""
    captured: dict = {}

    def fake_report_run(run_dir: Path, **options) -> Path:
        captured.update(run_dir=run_dir, **options)
        out = tmp_path / "report"
        out.mkdir(exist_ok=True)
        (out / "report.json").write_text(json.dumps({"missing": ["seepage_map"]}), encoding="utf-8")
        return out / "index.html"

    monkeypatch.setattr("hydromodpy.project.report.report_run", fake_report_run)
    return captured


def test_report_catchment_reads_a_run_directory(written, capsys, tmp_path) -> None:
    run_dir = tmp_path / "runs" / "base"
    run_dir.mkdir(parents=True)

    _main(["report", "catchment", str(run_dir)])

    assert written == {
        "run_dir": run_dir.resolve(),
        "preset": "research",
        "lang": "en",
        "overview_dir": None,
        "station": None,
        "strict": False,
    }
    out = capsys.readouterr().out
    assert f"html_report={tmp_path / 'report' / 'index.html'}" in out
    assert f"report_json={tmp_path / 'report' / 'report.json'}" in out
    assert "missing=seepage_map" in out


def test_report_catchment_passes_its_options(written, tmp_path) -> None:
    run_dir = tmp_path / "base"
    overview = tmp_path / "selune"
    run_dir.mkdir()
    overview.mkdir()

    _main(
        [
            "report",
            "catchment",
            str(run_dir),
            "--overview",
            str(overview),
            "--preset",
            "management",
            "--lang",
            "fr",
            "--station",
            "J0014010",
            "--strict",
        ]
    )

    assert written["preset"] == "management"
    assert written["lang"] == "fr"
    assert written["overview_dir"] == overview.resolve()
    assert written["station"] == "J0014010"
    assert written["strict"] is True


def test_report_catchment_json_output_names_the_missing_figures(written, capsys, tmp_path) -> None:
    run_dir = tmp_path / "base"
    run_dir.mkdir()

    _main(["report", "catchment", str(run_dir), "--format", "json"])

    document = json.loads(capsys.readouterr().out)
    assert document["schema"] == "hmp.report.catchment.v2"
    assert set(document["data"]) == {"html_report", "report_json", "missing"}
    assert document["data"]["missing"] == ["seepage_map"]


@pytest.mark.parametrize("table", ["[report]\nname = 'x'\n", "[layout]\nname = 'x'\n"])
def test_report_catchment_refuses_a_report_toml(written, capsys, tmp_path, table: str) -> None:
    config = tmp_path / "catchment_report.toml"
    config.write_text(table, encoding="utf-8")

    with pytest.raises(SystemExit) as exc_info:
        _main(["report", "catchment", str(config)])

    assert exc_info.value.code == EXIT_CONFIG
    assert REFUSED_REPORT_FILE in " ".join(capsys.readouterr().err.split())
    assert written == {}


@pytest.mark.parametrize(
    ("flag", "new_form"),
    [
        ("--run-overview", "hmp run <toml>"),
        ("--run-simulation", "hmp run <toml>"),
        ("--context-only", "hmp run <toml>"),
        ("--report-only", "hmp report catchment RUN"),
        ("--stream-run-logs", "hmp run <toml>"),
        ("--strict-figure-postflight", "--strict"),
    ],
)
def test_report_catchment_refuses_the_pipeline_flags(
    written, capsys, tmp_path, flag: str, new_form: str
) -> None:
    with pytest.raises(SystemExit) as exc_info:
        _main(["report", "catchment", str(tmp_path), flag])

    assert exc_info.value.code == EXIT_USAGE
    err = capsys.readouterr().err
    assert f"hmp report catchment {flag} is gone" in err
    assert new_form in err
    assert written == {}


def test_report_catchment_names_the_two_presets_when_given_another(capsys, tmp_path) -> None:
    with pytest.raises(SystemExit) as exc_info:
        _main(["report", "catchment", str(tmp_path), "--preset", "generic"])

    assert exc_info.value.code == EXIT_USAGE
    err = capsys.readouterr().err
    assert "research" in err
    assert "management" in err


@pytest.mark.allow_subprocess
def test_building_the_hmp_parser_loads_neither_the_report_engine_nor_pyplot() -> None:
    """Every ``hmp`` call builds the whole parser, so it must not import the engine.

    A fresh interpreter, because this process has imported both long ago.
    """
    probe = (
        "import sys\n"
        "from hydromodpy.cli.main import _build_parser\n"
        "_build_parser()\n"
        "heavy = ('hydromodpy.display.report', 'matplotlib.pyplot')\n"
        "print(','.join(name for name in heavy if name in sys.modules))\n"
    )
    loaded = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=True
    ).stdout.strip()

    assert loaded == "", f"building the hmp parser imported {loaded}"


def test_the_preset_choices_are_the_registered_presets() -> None:
    assert set(REPORT_PRESETS) == set(PRESETS), (
        "a report preset was added or removed in hydromodpy/display/report/presets.py; "
        "write the same names in REPORT_PRESETS, hydromodpy/cli/commands/report.py"
    )
