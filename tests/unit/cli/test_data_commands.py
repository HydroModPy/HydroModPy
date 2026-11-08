"""Unit tests for lightweight ``hmp data`` command wrappers."""

from __future__ import annotations

import pandas as pd

from tests._helpers.cli_runner import CliRunner


def _workspace(tmp_path):
    """Return ``tmp_path`` made a workspace: the commands resolve it before they call a verb."""
    (tmp_path / "data").mkdir(exist_ok=True)
    return tmp_path.resolve()


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
        "hydromodpy.data.request.cache_verbs.check_data_cache",
        fake_check_data_cache,
    )

    workspace = _workspace(tmp_path)

    result = CliRunner().invoke(
        ["data", "check", "--workspace", str(tmp_path), "--variable", "piezometry", "--fix"]
    )

    assert result.exit_code == 16
    assert calls == {"workspace": workspace, "variable": "piezometry", "fix": True}
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
        "hydromodpy.data.request.cache_verbs.list_data_cache",
        fake_list_data_cache,
    )

    workspace = _workspace(tmp_path)

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
    assert calls == {"workspace": workspace, "variable": "hydrometry", "provider": "custom"}
    assert "hydrometry" in result.stdout
    assert "internal" not in result.stdout


def test_data_ls_distinguishes_missing_and_empty_cache(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("hydromodpy.cli.helpers.resolve_workspace", lambda value: tmp_path)
    monkeypatch.setattr("hydromodpy.data.request.cache_verbs.list_data_cache", lambda *a, **k: None)
    missing = CliRunner().invoke(["data", "ls"])

    monkeypatch.setattr(
        "hydromodpy.data.request.cache_verbs.list_data_cache",
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

    monkeypatch.setattr("hydromodpy.data.request.cache_verbs.add_data_entry", fake_add_data_entry)

    result = CliRunner().invoke(["data", "add", str(tmp_path / "data.csv")])

    assert result.exit_code == 14
    assert called is False
    assert "--type is required" in result.stderr


def test_data_add_success_forwards_metadata(monkeypatch, tmp_path) -> None:
    src = tmp_path / "data.csv"
    src.write_text("datetime,value\n2020-01-01,1\n", encoding="utf-8")
    workspace = _workspace(tmp_path)
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

    monkeypatch.setattr("hydromodpy.data.request.cache_verbs.add_data_entry", fake_add_data_entry)

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
        "workspace_root": workspace,
        "project": None,
        "frozen": True,
    }
    assert "Added: hydrometry/custom/H1" in result.stdout


def test_data_archive_writes_the_cache_of_the_resolved_workspace(monkeypatch, tmp_path) -> None:
    calls: dict[str, object] = {}

    def fake_archive_data_cache(output, *, workspace_root):
        calls.update({"output": output, "workspace_root": workspace_root})
        return tmp_path / "cache.tar.gz"

    monkeypatch.setattr("hydromodpy.project.lock.archive_data_cache", fake_archive_data_cache)
    workspace = _workspace(tmp_path)

    result = CliRunner().invoke(
        ["data", "archive", "--to", "cache.tar.gz", "--workspace", str(tmp_path)]
    )

    assert result.exit_code == 0, result.stderr
    assert calls == {"output": "cache.tar.gz", "workspace_root": workspace}
    assert "Archived cache to" in result.stdout


def test_data_restore_unpacks_into_the_resolved_workspace(monkeypatch, tmp_path) -> None:
    calls: dict[str, object] = {}

    def fake_restore_data_cache(source, *, workspace_root, to):
        calls.update({"source": source, "workspace_root": workspace_root, "to": to})
        return workspace_root / "data" / "imported"

    monkeypatch.setattr("hydromodpy.project.lock.restore_data_cache", fake_restore_data_cache)
    workspace = _workspace(tmp_path)

    result = CliRunner().invoke(["data", "restore", "cache.tar.gz", "--workspace", str(tmp_path)])

    assert result.exit_code == 0, result.stderr
    assert calls == {"source": "cache.tar.gz", "workspace_root": workspace, "to": None}
