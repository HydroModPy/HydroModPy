"""The verbs of ``hmp data`` on the cache of a resolved workspace."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from hydromodpy.data.request import cache_verbs


def test_list_data_cache_uses_workspace_cache_and_filters(monkeypatch, tmp_path) -> None:
    workspace = tmp_path / "workspace"
    db_path = workspace / "data" / "cache.duckdb"
    db_path.parent.mkdir(parents=True)
    db_path.write_bytes(b"duckdb")
    calls: dict[str, object] = {}

    class FakeDataCatalog:
        def __init__(self, path: Path, *, read_only: bool = False) -> None:
            calls["db_path"] = path
            calls["read_only"] = read_only

        def __enter__(self):
            return self

        def __exit__(self, *exc_info: object) -> None:
            calls["closed"] = True

        def list_entries(self, *, variable: str | None, source: str | None) -> str:
            calls["filters"] = {"variable": variable, "source": source}
            return "rows"

    monkeypatch.setattr(
        "hydromodpy.data.registry.catalog_duckdb.DataCatalogDuckDB",
        FakeDataCatalog,
    )

    result = cache_verbs.list_data_cache(workspace, variable="dem", provider="ign")

    assert result == "rows"
    assert calls == {
        "db_path": db_path,
        "read_only": True,
        "filters": {"variable": "dem", "source": "ign"},
        "closed": True,
    }


def test_list_data_cache_returns_none_when_cache_is_absent(monkeypatch, tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    assert cache_verbs.list_data_cache(workspace, variable="dem", provider="ign") is None


def test_add_data_entry_timeseries_converts_and_registers_metadata(monkeypatch, tmp_path) -> None:
    workspace = tmp_path / "workspace"
    source = tmp_path / "station.csv"
    source.write_text("datetime,value\n2026-01-01,1.0\n", encoding="utf-8")
    spec = SimpleNamespace(
        name="hydrometry",
        kind="timeseries",
        unit="m3/s",
        pivot="wide_parquet",
    )
    calls: dict[str, object] = {}

    class FakeDataCatalog:
        def __init__(self, path: Path) -> None:
            calls["db_path"] = path

        def __enter__(self):
            return self

        def __exit__(self, *exc_info: object) -> None:
            calls["closed"] = True

        def register(self, **kwargs: object) -> None:
            calls["register"] = kwargs

    def fake_convert_timeseries_csv_to_parquet(src: Path, dest: Path) -> None:
        calls["convert"] = {"src": src, "dest": dest}
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"parquet")

    monkeypatch.setattr("hydromodpy.data.workspace.scaffold.VARIABLES", (spec,))
    monkeypatch.setattr(
        "hydromodpy.data.ingest.convert_timeseries_csv_to_parquet",
        fake_convert_timeseries_csv_to_parquet,
    )
    monkeypatch.setattr(
        "hydromodpy.data.registry.catalog_duckdb.DataCatalogDuckDB",
        FakeDataCatalog,
    )

    result = cache_verbs.add_data_entry(
        source,
        variable="hydrometry",
        provider="field",
        workspace_root=workspace,
    )

    dest = workspace / "data" / "blobs" / "hydrometry" / "field" / "station.parquet"
    assert result == {
        "variable": "hydrometry",
        "provider": "field",
        "station_id": "station",
        "dest": str(dest),
    }
    assert calls["db_path"] == workspace / "data" / "cache.duckdb"
    assert calls["convert"] == {"src": source.resolve(), "dest": dest}
    assert calls["register"] == {
        "variable": "hydrometry",
        "source": "field",
        "station_id": "station",
        "file_path": str(source.resolve()),
        "crs": None,
        "unit": "m3/s",
        "is_custom": True,
        "fetch_metadata": {"pivot_path": str(dest), "pivot_format": "wide_parquet"},
    }
    assert calls["closed"] is True


def test_check_data_cache_reports_the_issues_of_the_custom_files(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        "hydromodpy.data.workspace.custom_scan.check_custom",
        lambda root, *, variable: [(root / "data" / variable / "bad.csv", "no datetime")],
    )

    result = cache_verbs.check_data_cache(tmp_path, variable="hydrometry")

    assert result == {
        "workspace": str(tmp_path),
        "issues": [(str(tmp_path / "data" / "hydrometry" / "bad.csv"), "no datetime")],
        "fix_summary": None,
    }


def test_check_data_cache_fixes_the_cache_only_when_it_exists(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        "hydromodpy.data.workspace.custom_scan.check_custom", lambda root, *, variable: []
    )
    opened: list[Path] = []

    class FakeDataCatalog:
        def __init__(self, path: Path) -> None:
            opened.append(path)

        def __enter__(self):
            return self

        def __exit__(self, *exc_info: object) -> None:
            return None

        def check_and_fix(self) -> dict[str, int]:
            return {"dropped": 1, "refreshed": 0}

    monkeypatch.setattr(
        "hydromodpy.data.registry.catalog_duckdb.DataCatalogDuckDB", FakeDataCatalog
    )

    assert cache_verbs.check_data_cache(tmp_path, fix=True)["fix_summary"] is None
    db_path = tmp_path / "data" / "cache.duckdb"
    db_path.parent.mkdir(parents=True)
    db_path.write_bytes(b"duckdb")

    result = cache_verbs.check_data_cache(tmp_path, fix=True)

    assert result["fix_summary"] == {"dropped": 1, "refreshed": 0}
    assert opened == [db_path]
