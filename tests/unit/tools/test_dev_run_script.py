"""``python -m tools.dev run-script`` runs a script from its own folder, with the banner."""

from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from hydromodpy.core.logging import DEFAULT_VERBOSITY, set_verbosity
from tools.dev.__main__ import main


def test_the_script_runs_from_its_folder_with_its_arguments(monkeypatch, tmp_path) -> None:
    script = tmp_path / "prototype.py"
    script.write_text("print('prototype')\n", encoding="utf-8")
    captured: dict = {}

    def fake_run(cmd, cwd):
        captured["cmd"] = cmd
        captured["cwd"] = cwd
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr("tools.dev.run_script.subprocess.run", fake_run)
    monkeypatch.setattr("tools.dev.run_script.print_hydromodpy", lambda: None)
    monkeypatch.setattr(sys, "argv", ["tools.dev", "run-script", str(script), "--case", "demo"])

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 0
    assert captured["cmd"][1:] == [str(script.resolve()), "--case", "demo"]
    assert captured["cwd"] == str(tmp_path)


def test_the_banner_is_not_printed_when_quiet(monkeypatch, tmp_path) -> None:
    calls: list[None] = []
    monkeypatch.setattr("tools.dev.run_script.print_hydromodpy", lambda: calls.append(None))
    monkeypatch.setattr(
        "tools.dev.run_script.subprocess.run",
        lambda *a, **k: SimpleNamespace(returncode=0),
    )
    script = tmp_path / "proto.py"
    script.write_text("pass\n")

    monkeypatch.setenv("HMP_VERBOSITY", "quiet")
    try:
        with pytest.raises(SystemExit):
            main(["run-script", str(script)])
        assert calls == []

        monkeypatch.delenv("HMP_VERBOSITY")
        with pytest.raises(SystemExit):
            main(["run-script", str(script)])
        assert calls == [None]
    finally:
        set_verbosity(DEFAULT_VERBOSITY)
