"""Tests for newer top-level CLI verbs: calibrate, audit, viz, privacy verify."""

from __future__ import annotations

import importlib
import json
import os
import sys
from pathlib import Path

import pytest


def _load_main():
    return importlib.import_module("hydromodpy.cli.main")


def _run(monkeypatch, argv: list[str]) -> int:
    module = _load_main()
    monkeypatch.setattr(sys, "argv", argv)
    try:
        module.main()
    except SystemExit as exc:
        return int(exc.code or 0)
    return 0


def test_calibrate_missing_file_returns_not_found(monkeypatch) -> None:
    code = _run(monkeypatch, ["hmp", "calibrate", "/nonexistent/calib.toml"])
    assert code == 10


def test_calibrate_wrong_extension_returns_config(monkeypatch, tmp_path) -> None:
    bad = tmp_path / "calib.xml"
    bad.write_text("<?xml version='1.0'?>\n")
    code = _run(monkeypatch, ["hmp", "calibrate", str(bad)])
    assert code == 14


def test_audit_family_help_lists_actions(monkeypatch, capsys) -> None:
    code = _run(monkeypatch, ["hmp", "audit", "--help"])
    assert code == 0
    out = capsys.readouterr().out
    assert "list" in out and "verify" in out


def test_audit_list_without_catalog_exits_clean(monkeypatch, tmp_path) -> None:
    empty = tmp_path / "empty_ws"
    empty.mkdir()
    code = _run(monkeypatch, ["hmp", "audit", "list", "--workspace", str(empty)])
    assert code == 10


def test_viz_family_help_lists_serve(monkeypatch, capsys) -> None:
    code = _run(monkeypatch, ["hmp", "viz", "--help"])
    assert code == 0
    out = capsys.readouterr().out
    assert "serve" in out


def test_privacy_verify_missing_certificate_returns_not_found(monkeypatch, tmp_path) -> None:
    code = _run(monkeypatch, ["hmp", "privacy", "verify", str(tmp_path / "nope.json")])
    assert code == 10


def test_privacy_verify_invalid_json_returns_config(monkeypatch, tmp_path) -> None:
    bad = tmp_path / "cert.json"
    bad.write_text("{not valid")
    code = _run(monkeypatch, ["hmp", "privacy", "verify", str(bad)])
    assert code == 14


def test_privacy_verify_good_certificate_succeeds(monkeypatch, tmp_path, capsys) -> None:
    cert = tmp_path / "cert.json"
    cert.write_text(
        json.dumps(
            {
                "sim_id": "abc",
                "timestamp_utc": "2026-01-01T00:00:00+00:00",
                "operator": "tester",
                "reason": "test",
                "sha256_snapshot": "a" * 64,
            }
        )
    )
    os.chmod(cert, 0o600)
    code = _run(monkeypatch, ["hmp", "privacy", "verify", str(cert)])
    assert code == 0
    out = capsys.readouterr().out
    assert "verifies" in out.lower()


def test_privacy_verify_strict_rejects_wrong_permissions(monkeypatch, tmp_path) -> None:
    cert = tmp_path / "cert.json"
    cert.write_text(
        json.dumps(
            {
                "sim_id": "abc",
                "timestamp_utc": "2026-01-01T00:00:00+00:00",
                "operator": "tester",
                "reason": "test",
                "sha256_snapshot": "a" * 64,
            }
        )
    )
    os.chmod(cert, 0o644)
    code = _run(monkeypatch, ["hmp", "privacy", "verify", "--strict", str(cert)])
    assert code == 14
