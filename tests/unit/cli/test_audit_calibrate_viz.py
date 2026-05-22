"""Tests for newer top-level CLI verbs: calibrate, audit, viz, privacy verify."""

from __future__ import annotations

import importlib
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from hydromodpy.core.state.paths import CATALOG_FILENAME


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


def test_calibrate_success_forwards_resolved_path_and_prints_summary(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    import hydromodpy as hmp

    config = tmp_path / "calib.toml"
    config.write_text('[workflow]\nmode = "calibration"\n', encoding="utf-8")
    captured: dict[str, Path] = {}

    def fake_calibrate(path: Path):
        captured["path"] = path
        return SimpleNamespace(summary={"session_id": "s1", "best_objective": 0.25})

    monkeypatch.setattr(hmp, "calibrate", fake_calibrate)

    code = _run(monkeypatch, ["hmp", "calibrate", str(config)])

    assert code == 0
    assert captured["path"] == config.resolve()
    err = capsys.readouterr().err
    assert "Calibration finished: calib.toml" in err
    assert "session_id: s1" in err
    assert "best_objective: 0.25" in err


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


def test_audit_prune_dry_run_and_apply_forward_mode(monkeypatch, tmp_path, capsys) -> None:
    import hydromodpy as hmp

    calls: list[tuple[str, bool]] = []

    def fake_audit_prune(workspace, *, apply: bool):
        calls.append((workspace, apply))
        return {"config.replay": 2, "solver.run": 1}

    monkeypatch.setattr(hmp, "audit_prune", fake_audit_prune)

    dry_code = _run(monkeypatch, ["hmp", "audit", "prune", "--workspace", str(tmp_path)])
    dry_out = capsys.readouterr().out
    apply_code = _run(
        monkeypatch,
        ["hmp", "audit", "prune", "--workspace", str(tmp_path), "--apply"],
    )
    apply_out = capsys.readouterr().out

    assert dry_code == 0
    assert apply_code == 0
    assert calls == [(str(tmp_path), False), (str(tmp_path), True)]
    assert "(dry-run) config.replay: 2 row(s)" in dry_out
    assert "(dry-run) solver.run: 1 row(s)" in dry_out
    assert "(applied) config.replay: 2 row(s)" in apply_out


def test_audit_prune_missing_workspace_maps_to_not_found(monkeypatch, capsys) -> None:
    import hydromodpy as hmp

    def fake_audit_prune(workspace, *, apply: bool):
        del workspace, apply
        raise FileNotFoundError("missing catalog")

    monkeypatch.setattr(hmp, "audit_prune", fake_audit_prune)

    code = _run(monkeypatch, ["hmp", "audit", "prune", "--workspace", "/missing"])

    assert code == 10
    assert "missing catalog" in capsys.readouterr().err


def test_viz_family_help_lists_serve(monkeypatch, capsys) -> None:
    code = _run(monkeypatch, ["hmp", "viz", "--help"])
    assert code == 0
    out = capsys.readouterr().out
    assert "serve" in out


def test_report_render_calls_api_and_opens_browser_after_success(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    import hydromodpy as hmp

    html = tmp_path / "report.html"
    html.write_text("<html></html>", encoding="utf-8")
    calls: dict[str, object] = {}

    def fake_report(session_id: str, *, workspace: Path):
        calls["session_id"] = session_id
        calls["workspace"] = workspace
        return html

    def fake_open(uri: str) -> bool:
        calls["opened"] = uri
        return True

    monkeypatch.setattr(hmp, "report", fake_report)
    monkeypatch.setattr("webbrowser.open", fake_open)

    code = _run(
        monkeypatch,
        ["hmp", "report", "render", "session-1", "--workspace", str(tmp_path), "--open"],
    )

    assert code == 0
    assert calls["session_id"] == "session-1"
    assert calls["workspace"] == tmp_path
    assert calls["opened"] == html.as_uri()
    assert f"wrote {html}" in capsys.readouterr().err


def test_report_compare_filters_metric_name_without_changing_api_call(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    import hydromodpy as hmp

    (tmp_path / CATALOG_FILENAME).write_bytes(b"")
    calls: dict[str, object] = {}

    def fake_compare_pair(ref_a: str, ref_b: str, *, workspace: Path):
        calls["args"] = (ref_a, ref_b, workspace)
        return pd.DataFrame(
            {
                "metric_name": ["nse", "rmse", "kge"],
                "a": [0.8, 1.2, 0.7],
                "b": [0.9, 1.0, 0.6],
            }
        )

    monkeypatch.setattr(hmp, "compare_pair", fake_compare_pair)

    code = _run(
        monkeypatch,
        [
            "hmp",
            "report",
            "compare",
            "sim-a",
            "sim-b",
            "--workspace",
            str(tmp_path),
            "--variables",
            "nse,kge",
        ],
    )

    assert code == 0
    assert calls["args"] == ("sim-a", "sim-b", tmp_path.resolve())
    out = capsys.readouterr().out
    assert "nse" in out
    assert "kge" in out
    assert "rmse" not in out


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
