"""Contracts for shared atomic filesystem writes."""

from __future__ import annotations

import json
import os
from pathlib import Path

from hydromodpy.core.io.atomic import atomic_write_json, atomic_write_text, write_text_if_changed


def test_atomic_write_text_retries_transient_permission_error(
    tmp_path: Path,
    monkeypatch,
) -> None:
    target = tmp_path / "report.txt"
    original_replace = os.replace
    calls = {"count": 0}

    def flaky_replace(source, target_path):
        calls["count"] += 1
        if calls["count"] == 1:
            raise PermissionError("transient lock")
        original_replace(source, target_path)

    monkeypatch.setattr("hydromodpy.core.io.atomic.os.name", "nt")
    monkeypatch.setattr("hydromodpy.core.io.atomic.os.replace", flaky_replace)
    monkeypatch.setattr("hydromodpy.core.io.atomic.time.sleep", lambda _: None)

    out = atomic_write_text(target, "payload\n")

    assert out == target
    assert calls["count"] == 2
    assert target.read_text(encoding="utf-8") == "payload\n"
    assert not list(tmp_path.glob(".report.txt.tmp.*"))


def test_atomic_write_json_uses_stable_format(tmp_path: Path) -> None:
    target = atomic_write_json(tmp_path / "manifest.json", {"b": 2, "a": 1})

    assert json.loads(target.read_text(encoding="utf-8")) == {"a": 1, "b": 2}
    assert target.read_text(encoding="utf-8").splitlines()[1].strip().startswith('"a"')


def test_write_text_if_changed_skips_identical_content(tmp_path: Path) -> None:
    target = tmp_path / "index.rst"

    assert write_text_if_changed(target, "same\n") is True
    first_mtime = target.stat().st_mtime_ns
    assert write_text_if_changed(target, "same\n") is False
    assert target.stat().st_mtime_ns == first_mtime
