"""Unit tests for the ``--profile`` pyinstrument helpers.

The argparse grammar of the shared ``--profile`` flag is guarded in
``test_cli_conventions.py``; this module covers the behavioral helpers.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

from hydromodpy.cli.helpers import EXIT_CONFIG, profile_run, resolve_profile_output


def _burn(seconds: float = 0.02) -> None:
    deadline = time.perf_counter() + seconds
    while time.perf_counter() < deadline:
        sum(range(100))


def test_resolve_profile_output_disabled() -> None:
    assert resolve_profile_output(None, Path("/tmp/case.toml")) is None


def test_resolve_profile_output_default_path(tmp_path: Path) -> None:
    pytest.importorskip("pyinstrument")
    config = tmp_path / "case.toml"
    assert resolve_profile_output("", config) == config.with_suffix(".profile.html")


def test_resolve_profile_output_explicit_path(tmp_path: Path) -> None:
    pytest.importorskip("pyinstrument")
    out = tmp_path / "report.html"
    assert resolve_profile_output(str(out), Path("/tmp/case.toml")) == out


def test_resolve_profile_output_missing_pyinstrument(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setitem(sys.modules, "pyinstrument", None)
    with pytest.raises(SystemExit) as exc:
        resolve_profile_output("", tmp_path / "case.toml")
    assert exc.value.code == EXIT_CONFIG


def test_profile_run_noop_without_output() -> None:
    ran = False
    with profile_run(None):
        ran = True
    assert ran


def test_profile_run_writes_html(tmp_path: Path) -> None:
    pytest.importorskip("pyinstrument")
    out = tmp_path / "case.profile.html"
    with profile_run(out, description="hmp run case.toml (simulation)"):
        _burn()
    assert out.is_file()
    html = out.read_text(encoding="utf-8")
    assert "<html" in html.lower()
    assert "hmp run case.toml (simulation)" in html


def test_profile_run_writes_html_on_error(tmp_path: Path) -> None:
    pytest.importorskip("pyinstrument")
    out = tmp_path / "failed.profile.html"
    with pytest.raises(RuntimeError):
        with profile_run(out):
            _burn()
            raise RuntimeError("solver blew up")
    assert out.is_file()


def test_profile_run_report_failure_does_not_mask_run_error(tmp_path: Path) -> None:
    pytest.importorskip("pyinstrument")
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")
    out = blocker / "report.html"
    with pytest.raises(RuntimeError, match="solver blew up"):
        with profile_run(out):
            raise RuntimeError("solver blew up")


def test_profile_run_report_failure_does_not_fail_a_successful_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    pytest.importorskip("pyinstrument")
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")
    out = blocker / "report.html"
    with profile_run(out):
        _burn(0.005)
    assert "profile report write failed" in capsys.readouterr().err


def test_profile_run_missing_pyinstrument(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setitem(sys.modules, "pyinstrument", None)
    with pytest.raises(SystemExit) as exc:
        with profile_run(tmp_path / "x.html"):
            pass
    assert exc.value.code == EXIT_CONFIG
