"""Unit tests for the ``hmp data`` command wrappers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hydromodpy.data.provenance.sidecars import (
    FORMER_CACHE_DATABASE,
    CacheIndex,
    CacheRow,
    ScanReport,
)
from tests._helpers.cli_runner import CliRunner


def _workspace(tmp_path: Path) -> Path:
    """Return ``tmp_path`` made a workspace: the commands resolve it before they call a verb."""
    (tmp_path / "data").mkdir(exist_ok=True)
    return tmp_path.resolve()


def _row(data_root: Path, **fields: object) -> CacheRow:
    return CacheRow(path=data_root / "hydrometry" / "h.csv", **fields)  # type: ignore[arg-type]


def test_data_ls_forwards_filters_and_prints_the_columns_of_a_row(monkeypatch, tmp_path) -> None:
    workspace = _workspace(tmp_path)
    calls: dict[str, object] = {}
    row = _row(
        workspace / "data",
        variable="hydrometry",
        source="hubeau",
        station_id="H1",
        product="Q",
        license="Licence Ouverte",
    )

    def fake_list_data_cache(root, *, variable, provider):
        calls.update({"workspace": root, "variable": variable, "provider": provider})
        return ScanReport(data_root=workspace / "data", rows=(row,))

    monkeypatch.setattr("hydromodpy.data.request.cache_verbs.list_data_cache", fake_list_data_cache)

    result = CliRunner().invoke(
        ["data", "ls", "-w", str(tmp_path), "--variable", "hydrometry", "--provider", "hubeau"]
    )

    assert result.exit_code == 0, result.stderr
    assert calls == {"workspace": workspace, "variable": "hydrometry", "provider": "hubeau"}
    for word in ("hydrometry", "hubeau", "H1", "Licence Ouverte", "hydrometry/h.csv"):
        assert word in result.stdout
    assert "sha256" not in result.stdout


def test_data_ls_json_carries_every_field_of_a_row_and_no_database_column(
    monkeypatch, tmp_path
) -> None:
    workspace = _workspace(tmp_path)
    row = _row(workspace / "data", variable="dem", source="ign", sha256="ab" * 32, bytes=3)
    monkeypatch.setattr(
        "hydromodpy.data.request.cache_verbs.list_data_cache",
        lambda *a, **k: ScanReport(data_root=workspace / "data", rows=(row,)),
    )

    result = CliRunner().invoke(["data", "ls", "-w", str(tmp_path), "--format", "json"])

    document = json.loads(result.stdout)
    (item,) = document["data"]
    assert document["schema"] == "hmp.data.ls.v2"
    assert item["sha256"] == "ab" * 32 and item["bytes"] == 3 and item["license"] is None
    assert not {"id", "file_mtime", "is_custom", "file_path"} & set(item)


def test_data_ls_says_what_it_found_besides_the_rows(monkeypatch, tmp_path) -> None:
    workspace = _workspace(tmp_path)
    report = ScanReport(
        data_root=workspace / "data",
        user_files=(workspace / "data" / "mine.csv",),
        orphans=(workspace / "data" / "gone.csv.json",),
    )
    monkeypatch.setattr(
        "hydromodpy.data.request.cache_verbs.list_data_cache", lambda *a, **k: report
    )

    result = CliRunner().invoke(["data", "ls", "-w", str(tmp_path)])

    assert result.exit_code == 0, result.stderr
    assert "(empty cache" in result.stdout
    assert "1 user file(s)" in result.stdout
    assert "gone.csv.json: its file is gone" in result.stderr


def test_data_ls_distinguishes_a_missing_data_folder_from_an_empty_cache(tmp_path) -> None:
    (tmp_path / "projects").mkdir()
    missing = CliRunner().invoke(["data", "ls", "-w", str(tmp_path)])
    empty = CliRunner().invoke(["data", "ls", "-w", str(_workspace(tmp_path))])

    assert missing.exit_code == 0
    assert "(no cache found)" in missing.stdout
    assert empty.exit_code == 0
    assert "(empty cache" in empty.stdout


def test_data_ls_reads_the_sidecars_of_a_workspace(tmp_path) -> None:
    workspace = _workspace(tmp_path)
    fetched = workspace / "data" / "dem" / "dem_ign_a.tif"
    fetched.parent.mkdir()
    fetched.write_bytes(b"tif")
    CacheIndex(workspace / "data").record(fetched, variable="dem", source="ign")

    result = CliRunner().invoke(["data", "ls", "-w", str(tmp_path), "--format", "csv"])

    assert result.exit_code == 0, result.stderr
    assert "dem,ign" in result.stdout


def test_data_ls_refuses_a_data_folder_that_holds_the_former_database(tmp_path) -> None:
    workspace = _workspace(tmp_path)
    (workspace / "data" / FORMER_CACHE_DATABASE).write_bytes(b"duckdb")

    result = CliRunner().invoke(["data", "ls", "-w", str(tmp_path)])

    assert result.exit_code != 0
    assert "hmp workspace clean --data-cache" in result.stderr


def test_data_prune_asks_project_for_the_digests_it_keeps(monkeypatch, tmp_path) -> None:
    workspace = _workspace(tmp_path)
    cited = workspace / "data" / "dem" / "dem_ign_a.tif"
    cited.parent.mkdir()
    cited.write_bytes(b"tif")
    row = CacheIndex(workspace / "data").record(cited, variable="dem", source="ign")
    monkeypatch.setattr(
        "hydromodpy.project.data_cache.cited_input_digests",
        lambda root: frozenset({row.sha256}),
    )

    result = CliRunner().invoke(
        ["data", "prune", "--older-than", "0", "--delete-files", "-y", "-w", str(tmp_path)]
    )

    assert result.exit_code == 0, result.stderr
    assert "Pruned 0 row(s)" in result.stdout
    assert "Kept 1 file(s) that a run or a lockfile cites" in result.stdout
    assert str(cited.resolve()) in result.stdout
    assert cited.exists()


def test_data_prune_refuses_everything_when_a_run_cannot_be_read(monkeypatch, tmp_path) -> None:
    from hydromodpy.core.exceptions import DataCacheError

    workspace = _workspace(tmp_path)
    old = workspace / "data" / "dem" / "dem_ign_a.tif"
    old.parent.mkdir()
    old.write_bytes(b"tif")
    CacheIndex(workspace / "data").record(old, variable="dem", source="ign")

    def unreadable(root):
        raise DataCacheError("The inputs of the run r cannot be read, so nothing was pruned.")

    monkeypatch.setattr("hydromodpy.project.data_cache.cited_input_digests", unreadable)

    result = CliRunner().invoke(
        ["data", "prune", "--older-than", "0", "--delete-files", "-y", "-w", str(tmp_path)]
    )

    assert result.exit_code != 0
    assert "nothing was pruned" in result.stderr
    assert old.exists()


def test_data_remove_forwards_the_filters(monkeypatch, tmp_path) -> None:
    workspace = _workspace(tmp_path)
    calls: dict[str, object] = {}

    def fake_remove(root, **kwargs):
        calls.update({"workspace": root, **kwargs})
        return 2

    monkeypatch.setattr("hydromodpy.data.request.cache_verbs.remove_data_entries", fake_remove)

    result = CliRunner().invoke(
        ["data", "remove", "--variable", "dem", "--station-id", "S1", "--delete-files", "-y"]
        + ["-w", str(tmp_path)]
    )

    assert result.exit_code == 0, result.stderr
    assert calls == {
        "workspace": workspace,
        "variable": "dem",
        "provider": None,
        "station_id": "S1",
        "delete_files": True,
        "dry_run": False,
    }
    assert "Removed 2 row(s)" in result.stdout


def test_data_archive_writes_the_cache_of_the_resolved_workspace(monkeypatch, tmp_path) -> None:
    calls: dict[str, object] = {}

    def fake_archive_data_cache(output, *, workspace_root):
        calls.update({"output": output, "workspace_root": workspace_root})
        return tmp_path / "cache.tar.gz"

    monkeypatch.setattr(
        "hydromodpy.data.request.cache_verbs.archive_data_cache", fake_archive_data_cache
    )
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
        return workspace_root / "data"

    monkeypatch.setattr(
        "hydromodpy.data.request.cache_verbs.restore_data_cache", fake_restore_data_cache
    )
    workspace = _workspace(tmp_path)

    result = CliRunner().invoke(["data", "restore", "cache.tar.gz", "--workspace", str(tmp_path)])

    assert result.exit_code == 0, result.stderr
    assert calls == {"source": "cache.tar.gz", "workspace_root": workspace, "to": None}


@pytest.mark.parametrize(
    ("words", "said"),
    [
        (["data", "add", "x.csv", "--type", "dem"], "inputs/"),
        (["lock", "update"], "hmp data lock"),
        (["lock", "verify", "--strict"], "hmp data lock --check"),
    ],
    ids=["data add", "lock update", "lock verify"],
)
def test_a_removed_command_is_refused_with_the_form_that_replaces_it(
    words: list[str], said: str
) -> None:
    result = CliRunner().invoke(words)

    assert result.exit_code == 2
    assert said in result.stderr


def _data_cache_check(workspace: Path) -> dict:
    result = CliRunner().invoke(["doctor", "-w", str(workspace), "--format", "json"])
    checks = json.loads(result.stdout)["data"]["checks"]
    return next(check for check in checks if check["name"] == "data_cache")


def test_doctor_counts_the_rows_and_the_user_files_of_a_workspace(tmp_path) -> None:
    workspace = _workspace(tmp_path)
    fetched = workspace / "data" / "dem" / "dem_ign_a.tif"
    fetched.parent.mkdir()
    fetched.write_bytes(b"tif")
    CacheIndex(workspace / "data").record(fetched, variable="dem", source="ign")

    check = _data_cache_check(workspace)

    assert check["status"] == "OK"
    assert check["detail"] == "1 row(s), 0 user file(s)"


def test_doctor_reports_the_former_database_and_leaves_it_there(tmp_path) -> None:
    workspace = _workspace(tmp_path)
    database = workspace / "data" / FORMER_CACHE_DATABASE
    database.write_bytes(b"duckdb")

    check = _data_cache_check(workspace)

    assert check["status"] == "WARN"
    assert "hmp workspace clean --data-cache" in check["detail"]
    assert database.exists(), "the doctor reads and never repairs"


def test_doctor_names_a_sidecar_that_is_no_row(tmp_path) -> None:
    workspace = _workspace(tmp_path)
    (workspace / "data" / "dem").mkdir()
    (workspace / "data" / "dem" / "dem_ign_a.tif.json").write_text("not json", encoding="utf-8")

    check = _data_cache_check(workspace)

    assert check["status"] == "WARN"
    assert "dem_ign_a.tif.json" in check["detail"]
