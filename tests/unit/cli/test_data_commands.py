"""Unit tests for lightweight ``hmp data`` command wrappers."""

from __future__ import annotations

import pandas as pd

from tests._helpers.cli_runner import CliRunner


def test_data_check_fix_reports_summary_and_data_error(monkeypatch, tmp_path) -> None:
    calls: dict[str, object] = {}

    def fake_check_data_cache(workspace, *, variable, fix):
        calls.update({"workspace": workspace, "variable": variable, "fix": fix})
        return {
            "workspace": tmp_path,
            "fix_summary": {"dropped": 2, "refreshed": 3},
            "issues": [(tmp_path / "bad.csv", "missing datetime")],
        }

    monkeypatch.setattr(
        "hydromodpy.cli._workers.data.check_data_cache",
        fake_check_data_cache,
    )

    result = CliRunner().invoke(
        ["data", "check", "--workspace", str(tmp_path), "--variable", "piezometry", "--fix"]
    )

    assert result.exit_code == 16
    assert calls == {"workspace": str(tmp_path), "variable": "piezometry", "fix": True}
    assert "dropped 2 stale entries" in result.stdout
    assert "missing datetime" in result.stdout


def test_data_ls_forwards_filters_and_prints_business_columns(monkeypatch, tmp_path) -> None:
    calls: dict[str, object] = {}

    def fake_list_data_cache(workspace, *, variable, provider):
        calls.update({"workspace": workspace, "variable": variable, "provider": provider})
        return pd.DataFrame(
            {
                "variable": ["hydrometry"],
                "source": ["custom"],
                "station_id": ["H1"],
                "file_path": ["/tmp/h.csv"],
                "internal": ["hidden"],
            }
        )

    monkeypatch.setattr(
        "hydromodpy.cli._workers.data.list_data_cache",
        fake_list_data_cache,
    )

    result = CliRunner().invoke(
        [
            "data",
            "ls",
            "--workspace",
            str(tmp_path),
            "--variable",
            "hydrometry",
            "--provider",
            "custom",
        ]
    )

    assert result.exit_code == 0
    assert calls == {"workspace": str(tmp_path), "variable": "hydrometry", "provider": "custom"}
    assert "hydrometry" in result.stdout
    assert "internal" not in result.stdout


def test_data_ls_distinguishes_missing_and_empty_cache(monkeypatch) -> None:
    monkeypatch.setattr("hydromodpy.cli._workers.data.list_data_cache", lambda *a, **k: None)
    missing = CliRunner().invoke(["data", "ls"])

    monkeypatch.setattr(
        "hydromodpy.cli._workers.data.list_data_cache",
        lambda *a, **k: pd.DataFrame(),
    )
    empty = CliRunner().invoke(["data", "ls"])

    assert missing.exit_code == 0
    assert "(no cache found)" in missing.stdout
    assert empty.exit_code == 0
    assert "(empty cache" in empty.stdout


def test_data_add_requires_type_before_worker_call(monkeypatch, tmp_path) -> None:
    called = False

    def fake_add_data_entry(*args, **kwargs):
        nonlocal called
        called = True
        return {}

    monkeypatch.setattr("hydromodpy.cli._workers.data.add_data_entry", fake_add_data_entry)

    result = CliRunner().invoke(["data", "add", str(tmp_path / "data.csv")])

    assert result.exit_code == 14
    assert called is False
    assert "--type is required" in result.stderr


def test_data_add_success_forwards_metadata(monkeypatch, tmp_path) -> None:
    src = tmp_path / "data.csv"
    src.write_text("datetime,value\n2020-01-01,1\n", encoding="utf-8")
    calls: dict[str, object] = {}

    def fake_add_data_entry(file, **kwargs):
        calls["file"] = file
        calls["kwargs"] = kwargs
        return {
            "variable": kwargs["variable"],
            "provider": kwargs["provider"],
            "station_id": kwargs["station_id"],
            "dest": tmp_path / "workspace" / "data.csv",
        }

    monkeypatch.setattr("hydromodpy.cli._workers.data.add_data_entry", fake_add_data_entry)

    result = CliRunner().invoke(
        [
            "data",
            "add",
            str(src),
            "--type",
            "hydrometry",
            "--provider",
            "custom",
            "--crs",
            "EPSG:2154",
            "--unit",
            "m3/s",
            "--station-id",
            "H1",
            "--workspace",
            str(tmp_path),
            "--frozen",
        ]
    )

    assert result.exit_code == 0
    assert calls["file"] == str(src)
    assert calls["kwargs"] == {
        "variable": "hydrometry",
        "provider": "custom",
        "crs": "EPSG:2154",
        "unit": "m3/s",
        "station_id": "H1",
        "workspace": str(tmp_path),
        "project": None,
        "frozen": True,
    }
    assert "Added: hydrometry/custom/H1" in result.stdout


def test_data_import_dry_run_forwards_options(monkeypatch, tmp_path) -> None:
    package = tmp_path / "run.hmp"
    package.write_bytes(b"stub")
    calls: dict[str, object] = {}

    def fake_import_package(package_path, **kwargs):
        calls["package"] = package_path
        calls["kwargs"] = kwargs
        return "sim-123"

    monkeypatch.setattr("hydromodpy.cli._workers.data.import_package", fake_import_package)

    result = CliRunner().invoke(
        [
            "data",
            "import",
            str(package),
            "--workspace",
            str(tmp_path),
            "--as",
            "ProjectA",
            "--dry-run",
            "--force",
        ]
    )

    assert result.exit_code == 0
    assert calls["package"] == str(package)
    assert calls["kwargs"] == {
        "workspace": str(tmp_path),
        "as_project": "ProjectA",
        "dry_run": True,
        "force": True,
    }
    assert "Dry-run OK" in result.stdout
