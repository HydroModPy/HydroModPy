from __future__ import annotations

import importlib
from pathlib import Path

import pytest


def _load_module():
    return importlib.import_module("hydromodpy.__main__")


def _capture_pytest_invocation(
    monkeypatch,
    argv: list[str],
) -> tuple[list[str], dict[str, str] | None]:
    module = _load_module()
    captured: dict[str, object] = {}

    def _fake_call(args: list[str], env: dict[str, str] | None = None) -> int:
        captured["args"] = list(args)
        captured["env"] = None if env is None else dict(env)
        return 0

    monkeypatch.setattr(module.subprocess, "call", _fake_call)
    monkeypatch.setattr(module.sys, "argv", argv)

    with pytest.raises(SystemExit) as exc_info:
        module.main()

    assert exc_info.value.code == 0
    return captured["args"], captured.get("env")


def test_hmp_regression_fast_mf6_builds_fast_tier_selection(monkeypatch) -> None:
    args, _ = _capture_pytest_invocation(
        monkeypatch,
        ["hmp", "test", "regression", "--fast", "--mf6"],
    )

    assert args[:3] == [str(Path(importlib.import_module("hydromodpy.__main__").sys.executable)), "-m", "pytest"]
    assert any(str(arg).endswith(str(Path("tests") / "regression" / "fast")) for arg in args)
    marker_index = args.index("-m", 3)
    assert args[marker_index + 1] == "fast and mf6"


def test_hmp_regression_normal_alias_maps_to_fast_tier(monkeypatch) -> None:
    args, _ = _capture_pytest_invocation(
        monkeypatch,
        ["hmp", "test", "regression", "--normal"],
    )

    assert args[:3] == [str(Path(importlib.import_module("hydromodpy.__main__").sys.executable)), "-m", "pytest"]
    assert any(str(arg).endswith(str(Path("tests") / "regression" / "fast")) for arg in args)
    marker_index = args.index("-m", 3)
    assert args[marker_index + 1] == "fast"


def test_hmp_validation_fast_steady_builds_validation_marker_selection(monkeypatch) -> None:
    args, _ = _capture_pytest_invocation(
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


def test_hmp_test_uses_external_pytest_basetemp(monkeypatch, tmp_path: Path) -> None:
    scratch_root = tmp_path / "external_scratch"
    monkeypatch.setenv("HYDROMODPY_TEST_SCRATCH_ROOT", str(scratch_root))

    args, env = _capture_pytest_invocation(
        monkeypatch,
        ["hmp", "test", "unit"],
    )

    assert env is not None
    assert "--basetemp" in args
    basetemp_index = args.index("--basetemp")
    basetemp_path = Path(args[basetemp_index + 1])
    assert basetemp_path.parent == (scratch_root / "pytest").resolve()
    assert basetemp_path.name.startswith("cli_")
    assert env["HYDROMODPY_TEST_SCRATCH_ROOT"] == str(scratch_root.resolve())
    assert env["PYTEST_DEBUG_TEMPROOT"] == str((scratch_root / "pytest").resolve())
    assert env["TMPDIR"] == str((scratch_root / "tmp").resolve())
    assert env["TMP"] == str((scratch_root / "tmp").resolve())
    assert env["TEMP"] == str((scratch_root / "tmp").resolve())
