"""Unit tests for the shared ``--profile`` flag and pyinstrument wiring."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import pytest

from hydromodpy.cli import _conventions
from hydromodpy.cli.helpers import EXIT_CONFIG, profile_run, resolve_profile_output
from hydromodpy.cli.main import _build_parser


def test_profile_parser_grammar() -> None:
    parser = argparse.ArgumentParser(add_help=False, parents=[_conventions.profile_parser()])
    assert parser.parse_args([]).profile is None
    assert parser.parse_args(["--profile"]).profile == ""
    assert parser.parse_args(["--profile", "out.html"]).profile == "out.html"


@pytest.mark.parametrize("verb", ["run", "calibrate"])
def test_run_and_calibrate_offer_profile(verb: str) -> None:
    args = _build_parser().parse_args([verb, "config.toml", "--profile"])
    assert args.profile == ""


def test_resolve_profile_output_disabled() -> None:
    assert resolve_profile_output(None, Path("/tmp/case.toml")) is None


def test_resolve_profile_output_default_path(tmp_path: Path) -> None:
    config = tmp_path / "case.toml"
    assert resolve_profile_output("", config) == config.with_suffix(".profile.html")


def test_resolve_profile_output_explicit_path(tmp_path: Path) -> None:
    out = tmp_path / "report.html"
    assert resolve_profile_output(str(out), Path("/tmp/case.toml")) == out


def test_profile_run_noop_without_output() -> None:
    ran = False
    with profile_run(None):
        ran = True
    assert ran


def test_profile_run_writes_html(tmp_path: Path) -> None:
    pytest.importorskip("pyinstrument")
    out = tmp_path / "case.profile.html"
    with profile_run(out):
        deadline = time.perf_counter() + 0.02
        while time.perf_counter() < deadline:
            sum(range(100))
    assert out.is_file()
    assert "<html" in out.read_text(encoding="utf-8").lower()


def test_profile_run_writes_html_on_error(tmp_path: Path) -> None:
    pytest.importorskip("pyinstrument")
    out = tmp_path / "failed.profile.html"
    with pytest.raises(RuntimeError):
        with profile_run(out):
            deadline = time.perf_counter() + 0.02
            while time.perf_counter() < deadline:
                sum(range(100))
            raise RuntimeError("solver blew up")
    assert out.is_file()


def test_profile_run_missing_pyinstrument(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setitem(sys.modules, "pyinstrument", None)
    with pytest.raises(SystemExit) as exc:
        with profile_run(tmp_path / "x.html"):
            pass
    assert exc.value.code == EXIT_CONFIG
