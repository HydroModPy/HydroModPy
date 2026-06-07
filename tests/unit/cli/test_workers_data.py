"""Unit tests for private ``hmp data`` workers."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from hydromodpy.cli._workers import data as data_worker


def test_list_data_cache_uses_workspace_cache_and_filters(monkeypatch, tmp_path) -> None:
    workspace = tmp_path / "workspace"
    db_path = workspace / "data" / "cache.duckdb"
    db_path.parent.mkdir(parents=True)
    db_path.write_bytes(b"duckdb")
    calls: dict[str, object] = {}

    class FakeDataCatalog:
        def __init__(self, path: Path) -> None:
            calls["db_path"] = path

        def __enter__(self):
            return self

        def __exit__(self, *exc_info: object) -> None:
            calls["closed"] = True

        def list_entries(self, *, variable: str | None, source: str | None) -> str:
            calls["filters"] = {"variable": variable, "source": source}
            return "rows"

    monkeypatch.setattr("hydromodpy.cli.helpers.resolve_workspace", lambda value: workspace)
    monkeypatch.setattr(
        "hydromodpy.data.registry.catalog_duckdb.DataCatalogDuckDB",
        FakeDataCatalog,
    )

    result = data_worker.list_data_cache("ws-ref", variable="dem", provider="ign")

    assert result == "rows"
    assert calls == {
        "db_path": db_path,
        "filters": {"variable": "dem", "source": "ign"},
        "closed": True,
    }


def test_list_data_cache_returns_none_when_cache_is_absent(monkeypatch, tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    monkeypatch.setattr("hydromodpy.cli.helpers.resolve_workspace", lambda value: workspace)

    assert data_worker.list_data_cache("ws-ref", variable="dem", provider="ign") is None


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

    def fake_resolve_workspace(value: str | None) -> Path:
        calls["workspace_arg"] = value
        return workspace

    def fake_convert_timeseries_csv_to_parquet(src: Path, dest: Path) -> None:
        calls["convert"] = {"src": src, "dest": dest}
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"parquet")

    monkeypatch.setattr("hydromodpy.cli.helpers.resolve_workspace", fake_resolve_workspace)
    monkeypatch.setattr("hydromodpy.data.scaffold.VARIABLES", (spec,))
    monkeypatch.setattr(
        "hydromodpy.data.adapters.convert_timeseries_csv_to_parquet",
        fake_convert_timeseries_csv_to_parquet,
    )
    monkeypatch.setattr(
        "hydromodpy.data.registry.catalog_duckdb.DataCatalogDuckDB",
        FakeDataCatalog,
    )

    result = data_worker.add_data_entry(
        source,
        variable="hydrometry",
        provider="field",
        workspace="named-workspace",
    )

    dest = workspace / "data" / "blobs" / "hydrometry" / "field" / "station.parquet"
    assert result == {
        "variable": "hydrometry",
        "provider": "field",
        "station_id": "station",
        "dest": str(dest),
    }
    assert calls["workspace_arg"] == "named-workspace"
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
