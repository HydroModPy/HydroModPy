from __future__ import annotations

import importlib
from pathlib import Path

import pytest


def _load_module():
    return importlib.import_module("hydromodpy.__main__")


def _capture_pytest_args(monkeypatch, argv: list[str]) -> list[str]:
    module = _load_module()
    captured: dict[str, list[str]] = {}

    def _fake_call(args: list[str]) -> int:
        captured["args"] = list(args)
        return 0

    monkeypatch.setattr(module.subprocess, "call", _fake_call)
    monkeypatch.setattr(module.sys, "argv", argv)

    with pytest.raises(SystemExit) as exc_info:
        module.main()

    assert exc_info.value.code == 0
    return captured["args"]


def test_hmp_regression_fast_mf6_builds_fast_tier_selection(monkeypatch) -> None:
    args = _capture_pytest_args(
        monkeypatch,
        ["hmp", "test", "regression", "--fast", "--mf6"],
    )

    assert args[:3] == [str(Path(importlib.import_module("hydromodpy.__main__").sys.executable)), "-m", "pytest"]
    assert any(str(arg).endswith(str(Path("tests") / "regression" / "fast")) for arg in args)
    marker_index = args.index("-m", 3)
    assert args[marker_index + 1] == "fast and mf6"


def test_hmp_regression_normal_alias_maps_to_fast_tier(monkeypatch) -> None:
    args = _capture_pytest_args(
        monkeypatch,
        ["hmp", "test", "regression", "--normal"],
    )

    assert args[:3] == [str(Path(importlib.import_module("hydromodpy.__main__").sys.executable)), "-m", "pytest"]
    assert any(str(arg).endswith(str(Path("tests") / "regression" / "fast")) for arg in args)
    marker_index = args.index("-m", 3)
    assert args[marker_index + 1] == "fast"


def test_hmp_validation_fast_steady_builds_validation_marker_selection(monkeypatch) -> None:
    args = _capture_pytest_args(
        monkeypatch,
        ["hmp", "test", "validation", "--fast", "--steady"],
    )

    assert args[:3] == [str(Path(importlib.import_module("hydromodpy.__main__").sys.executable)), "-m", "pytest"]
    assert any(str(arg).endswith(str(Path("tests") / "validation")) for arg in args)
    marker_index = args.index("-m", 3)
    assert args[marker_index + 1] == "validation and fast and steady"


def test_hmp_validation_rejects_extensive(monkeypatch) -> None:
    module = _load_module()
    captured = {"called": False}

    def _fake_call(args: list[str]) -> int:
        captured["called"] = True
        return 0

    monkeypatch.setattr(module.subprocess, "call", _fake_call)
    monkeypatch.setattr(module.sys, "argv", ["hmp", "test", "validation", "--extensive"])

    with pytest.raises(SystemExit) as exc_info:
        module.main()

    assert exc_info.value.code == 2
    assert captured["called"] is False
