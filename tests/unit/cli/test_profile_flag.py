"""The ``--profile`` helpers: where the HTML report goes and what a failure does to the run.

The argparse grammar of the shared ``--profile`` flag is guarded in
``test_cli_conventions.py``; this module covers the behavioral helpers.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

from hydromodpy.cli.exit_codes import EXIT_CONFIG
from hydromodpy.cli.profiling import profile_arg_from_toml, profile_run, resolve_profile_output


def _burn(seconds: float = 0.02) -> None:
    deadline = time.perf_counter() + seconds
    while time.perf_counter() < deadline:
        sum(range(100))


def test_arg_from_toml() -> None:
    assert profile_arg_from_toml({}) is None
    assert profile_arg_from_toml({"workflow": {"mode": "simulation"}}) is None
    assert profile_arg_from_toml({"workflow": {"profile": False}}) is None
    assert profile_arg_from_toml({"workflow": {"profile": ""}}) is None
    assert profile_arg_from_toml({"workflow": {"profile": True}}) == ""
    assert profile_arg_from_toml({"workflow": {"profile": "perf.html"}}) == "perf.html"


@pytest.mark.parametrize(
    ("flag", "expected"),
    [
        pytest.param("", "case.profile.html", id="bare flag"),
        pytest.param("report.html", "report.html", id="named file"),
    ],
)
def test_profile_output_path(tmp_path: Path, flag: str, expected: str) -> None:
    pytest.importorskip("pyinstrument")
    config = tmp_path / "case.toml"
    named = str(tmp_path / flag) if flag else ""
    assert resolve_profile_output(named, config) == tmp_path / expected


def test_output_without_pyinstrument(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setitem(sys.modules, "pyinstrument", None)
    with pytest.raises(SystemExit) as exc:
        resolve_profile_output("", tmp_path / "case.toml")
    assert exc.value.code == EXIT_CONFIG


def test_html_written(tmp_path: Path) -> None:
    pytest.importorskip("pyinstrument")
    out = tmp_path / "case.profile.html"
    with profile_run(out, description="hmp run case.toml (simulation)"):
        _burn()
    assert out.is_file()
    html = out.read_text(encoding="utf-8")
    assert "<html" in html.lower()
    assert "hmp run case.toml (simulation)" in html


def test_html_written_on_error(tmp_path: Path) -> None:
    pytest.importorskip("pyinstrument")
    out = tmp_path / "failed.profile.html"
    with pytest.raises(RuntimeError):
        with profile_run(out):
            _burn()
            raise RuntimeError("solver blew up")
    assert out.is_file()


def test_report_failure_keeps_run_error(tmp_path: Path) -> None:
    pytest.importorskip("pyinstrument")
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")
    out = blocker / "report.html"
    with pytest.raises(RuntimeError, match="solver blew up"):
        with profile_run(out):
            raise RuntimeError("solver blew up")


def test_report_failure_keeps_success(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    pytest.importorskip("pyinstrument")
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")
    out = blocker / "report.html"
    with profile_run(out):
        _burn(0.005)
    assert "profile report write failed" in capsys.readouterr().err


def test_run_without_pyinstrument(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setitem(sys.modules, "pyinstrument", None)
    with pytest.raises(SystemExit) as exc:
        with profile_run(tmp_path / "x.html"):
            pass
    assert exc.value.code == EXIT_CONFIG
