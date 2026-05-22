"""Unit tests for ``hmp data export``."""

from __future__ import annotations

from pathlib import Path

from hydromodpy.core.state.paths import CATALOG_FILENAME
from tests._helpers.cli_runner import CliRunner


def test_data_export_missing_catalog_returns_not_found(tmp_path) -> None:
    project = tmp_path / "project"
    project.mkdir()

    result = CliRunner().invoke(["data", "export", str(project), "--list"])

    assert result.exit_code == 10
    assert f"No catalog found at {project.resolve()}" in result.stderr


def test_data_export_sim_defaults_to_csv_and_prints_export_count(monkeypatch, tmp_path) -> None:
    project = tmp_path / "ProjectA"
    project.mkdir()
    (project / CATALOG_FILENAME).write_bytes(b"catalog")
    calls: dict[str, object] = {}

    class FakeConnection:
        def execute(self, query: str, params: list[str]):
            calls["query"] = {"sql": query, "params": params}
            return self

        def fetchone(self) -> tuple[str]:
            return ("run-one",)

    class FakeCatalog:
        def __init__(self, root: Path) -> None:
            calls["catalog_root"] = root
            self.connection = FakeConnection()

        def resolve(self, sim_ref: str, *, project: str | None = None) -> str:
            calls["resolve"] = {"sim_ref": sim_ref, "project": project}
            return "sim-001"

        def export(
            self,
            sim_id: str,
            variable: str,
            fmt: str,
            out: Path,
            **kwargs: object,
        ) -> None:
            calls["export"] = {
                "sim_id": sim_id,
                "variable": variable,
                "fmt": fmt,
                "out": out,
                "kwargs": kwargs,
            }
            out.write_text("csv", encoding="utf-8")

        def close(self) -> None:
            calls["closed"] = True

    monkeypatch.setattr("hydromodpy.results.catalog.SimulationCatalog", FakeCatalog)

    result = CliRunner().invoke(["data", "export", str(project), "--sim", "run-one"])

    out = project.resolve() / "exports" / "run-one" / "timeseries.csv"
    assert result.exit_code == 0
    assert calls["catalog_root"] == project.resolve()
    assert calls["resolve"] == {"sim_ref": "run-one", "project": "ProjectA"}
    assert calls["query"]["params"] == ["sim-001"]
    assert calls["export"] == {
        "sim_id": "sim-001",
        "variable": "*",
        "fmt": "csv",
        "out": out,
        "kwargs": {},
    }
    assert calls["closed"] is True
    assert out.is_file()
    assert str(out) in result.stderr
    assert "Exported 1 file(s)" in result.stderr


def test_data_export_geotiff_requires_resolution_and_closes_catalog(
    monkeypatch,
    tmp_path,
) -> None:
    project = tmp_path / "ProjectA"
    project.mkdir()
    (project / CATALOG_FILENAME).write_bytes(b"catalog")
    calls: dict[str, object] = {}

    class FakeConnection:
        def execute(self, query: str, params: list[str]):
            del query, params
            return self

        def fetchone(self) -> tuple[str]:
            return ("run-one",)

    class FakeCatalog:
        def __init__(self, root: Path) -> None:
            calls["catalog_root"] = root
            self.connection = FakeConnection()

        def resolve(self, sim_ref: str, *, project: str | None = None) -> str:
            calls["resolve"] = {"sim_ref": sim_ref, "project": project}
            return "sim-001"

        def export(self, *args: object, **kwargs: object) -> None:
            calls["export_called"] = True

        def close(self) -> None:
            calls["closed"] = True

    monkeypatch.setattr("hydromodpy.results.catalog.SimulationCatalog", FakeCatalog)

    result = CliRunner().invoke(["data", "export", str(project), "--sim", "run-one", "--geotiff"])

    assert result.exit_code == 14
    assert calls == {
        "catalog_root": project.resolve(),
        "resolve": {"sim_ref": "run-one", "project": "ProjectA"},
        "closed": True,
    }
    assert "--resolution is required with --geotiff" in result.stderr
