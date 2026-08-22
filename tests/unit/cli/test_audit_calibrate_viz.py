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

from hydromodpy.core.state.paths import catalog_path_for


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
    captured: dict[str, object] = {}

    def fake_calibrate(path: Path, *, phase=None):
        captured["path"] = path
        captured["phase"] = phase
        return SimpleNamespace(summary={"session_id": "s1", "best_objective": 0.25})

    monkeypatch.setattr(hmp, "calibrate", fake_calibrate)

    code = _run(monkeypatch, ["hmp", "calibrate", str(config)])

    assert code == 0
    assert captured["path"] == config.resolve()
    assert captured["phase"] is None
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


def test_audit_prune_is_gone(monkeypatch, capsys) -> None:
    """``hmp audit prune`` was removed with the never-written retention table."""
    code = _run(monkeypatch, ["hmp", "audit", "prune"])

    assert code == 2
    assert "invalid choice: 'prune'" in capsys.readouterr().err


def test_viz_family_help_lists_actions(monkeypatch, capsys) -> None:
    code = _run(monkeypatch, ["hmp", "viz", "--help"])
    assert code == 0
    out = capsys.readouterr().out
    assert "show" in out
    assert "gallery" in out
    assert "serve" not in out


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
    assert Path(calls["workspace"]) == tmp_path
    assert calls["opened"] == html.as_uri()
    assert f"wrote {html}" in capsys.readouterr().err


def test_report_compare_filters_metric_name_without_changing_api_call(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    import hydromodpy as hmp

    catalog_path = catalog_path_for(tmp_path)
    catalog_path.parent.mkdir(parents=True, exist_ok=True)
    catalog_path.write_bytes(b"")
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


def test_calibrate_forwards_the_selected_phase(monkeypatch, tmp_path) -> None:
    """``--phase`` reaches the API, which is what runs one stage of a chain."""
    import hydromodpy as hmp

    config = tmp_path / "calib.toml"
    config.write_text('[workflow]\nmode = "calibration"\n', encoding="utf-8")
    captured: dict[str, object] = {}

    def fake_calibrate(path: Path, *, phase=None):
        captured["phase"] = phase
        return SimpleNamespace(summary={})

    monkeypatch.setattr(hmp, "calibrate", fake_calibrate)

    code = _run(monkeypatch, ["hmp", "calibrate", str(config), "--phase", "transient_sy"])

    assert code == 0
    assert captured["phase"] == "transient_sy"


def test_calibrate_lists_the_phases_without_running(monkeypatch, tmp_path, capsys) -> None:
    import hydromodpy as hmp

    config = tmp_path / "calib.toml"
    config.write_text('[workflow]\nmode = "calibration"\n', encoding="utf-8")
    calls: list[dict] = []

    def fake_calibrate(path: Path, *, phase=None, list_phases=False):
        calls.append({"phase": phase, "list_phases": list_phases})
        return [
            {
                "name": "steady_k_over_r",
                "description": "zero of the signed gap",
                "method": "bisection",
                "parameters": ["K"],
                "depends_on": None,
                "freeze_on_success": True,
            }
        ]

    monkeypatch.setattr(hmp, "calibrate", fake_calibrate)

    code = _run(monkeypatch, ["hmp", "calibrate", str(config), "--list-phases"])

    assert code == 0
    # Listing must not run anything.
    assert calls == [{"phase": None, "list_phases": True}]
    assert "steady_k_over_r" in capsys.readouterr().out


def test_calibrate_refusal_exits_with_the_calibration_code(monkeypatch, tmp_path, capsys) -> None:
    """A refusal of the method is typed, so it exits 21 and not 1."""
    import hydromodpy as hmp
    from hydromodpy.core.exceptions import CalibrationError

    config = tmp_path / "calib.toml"
    config.write_text('[workflow]\nmode = "calibration"\n', encoding="utf-8")

    def fake_calibrate(path: Path, *, phase=None):
        raise CalibrationError("residual keeps a constant sign over the bracket")

    monkeypatch.setattr(hmp, "calibrate", fake_calibrate)

    code = _run(monkeypatch, ["hmp", "calibrate", str(config)])

    assert code == 21
    assert "residual keeps a constant sign" in capsys.readouterr().err


def test_calibrate_list_phases_reports_an_unreadable_config(monkeypatch, tmp_path, capsys) -> None:
    """``--list-phases`` on a file that cannot be read exits 14, not 0."""
    import hydromodpy as hmp
    from hydromodpy.core.exceptions import ConfigError

    config = tmp_path / "calib.toml"
    config.write_text('[workflow]\nmode = "calibration"\n', encoding="utf-8")

    def fake_calibrate(path: Path, *, phase=None, list_phases=False):
        raise ConfigError("calib.toml: 1 validation error for CalibrationConfig")

    monkeypatch.setattr(hmp, "calibrate", fake_calibrate)

    code = _run(monkeypatch, ["hmp", "calibrate", str(config), "--list-phases"])

    assert code == 14
    assert "validation error" in capsys.readouterr().err
