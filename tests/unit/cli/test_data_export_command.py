"""Unit tests for ``hmp data export``."""

from __future__ import annotations

from pathlib import Path

from hydromodpy.core.state.paths import catalog_path_for, share_dir_for
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
    catalog_path = catalog_path_for(project)
    catalog_path.parent.mkdir(parents=True, exist_ok=True)
    catalog_path.write_bytes(b"catalog")
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

        def export(self, ref: str, spec) -> Path:
            calls["export"] = {"ref": ref, "var": spec.var, "dest": spec.dest}
            spec.dest.write_text("csv", encoding="utf-8")
            return spec.dest

        def close(self) -> None:
            calls["closed"] = True

    monkeypatch.setattr("hydromodpy.results.catalog.Catalog", FakeCatalog)

    result = CliRunner().invoke(["data", "export", str(project), "--sim", "run-one"])

    out = share_dir_for(project.resolve()) / "run-one" / "timeseries.csv"
    assert result.exit_code == 0
    assert calls["catalog_root"] == project.resolve()
    assert calls["resolve"] == {"sim_ref": "run-one", "project": "ProjectA"}
    assert calls["query"]["params"] == ["sim-001"]
    assert calls["export"] == {"ref": "sim-001", "var": "*", "dest": out}
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
    catalog_path = catalog_path_for(project)
    catalog_path.parent.mkdir(parents=True, exist_ok=True)
    catalog_path.write_bytes(b"catalog")
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

    monkeypatch.setattr("hydromodpy.results.catalog.Catalog", FakeCatalog)

    result = CliRunner().invoke(["data", "export", str(project), "--sim", "run-one", "--geotiff"])

    assert result.exit_code == 14
    assert calls == {
        "catalog_root": project.resolve(),
        "resolve": {"sim_ref": "run-one", "project": "ProjectA"},
        "closed": True,
    }
    assert "--resolution is required with --geotiff" in result.stderr


def test_data_export_list_names_the_fields_of_the_last_live_run(monkeypatch, tmp_path) -> None:
    import pandas as pd

    project = tmp_path / "ProjectA"
    project.mkdir()
    catalog_path = catalog_path_for(project)
    catalog_path.parent.mkdir(parents=True, exist_ok=True)
    catalog_path.write_bytes(b"catalog")
    calls: dict[str, object] = {}

    class FakeArray:
        def list_fields(self) -> list[str]:
            return ["drain", "head", "outflow_drain"]

    class FakeRun:
        array = FakeArray()

    class FakeZarr:
        root = {"geographic": {"watershed_dem": object()}}

        def close(self) -> None:
            calls["zarr_closed"] = True

    class FakeCatalog:
        def __init__(self, root: Path) -> None:
            del root

        def list_simulations(self, *, project: str | None = None):
            del project
            return pd.DataFrame(
                [
                    {
                        "sim_id": "sim-001",
                        "name": "run-one",
                        "solver": "modflow6",
                        "status": "completed",
                        "created_at": "2026-09-16 13:54",
                    },
                    {
                        "sim_id": "sim-002",
                        "name": "run-two",
                        "solver": "modflow6",
                        "status": "trashed",
                        "created_at": "2026-09-16 14:07",
                    },
                ]
            )

        def open_zarr(self, sim_id: str) -> FakeZarr:
            calls["open_zarr"] = sim_id
            return FakeZarr()

        def __getitem__(self, ref: str) -> FakeRun:
            calls["run_ref"] = ref
            return FakeRun()

        def list_geographic_features(self, sim_id: str) -> list[str]:
            calls["features_for"] = sim_id
            return ["watershed"]

        def close(self) -> None:
            calls["closed"] = True

    monkeypatch.setattr("hydromodpy.results.catalog.Catalog", FakeCatalog)

    result = CliRunner().invoke(["data", "export", str(project), "--list"])

    assert result.exit_code == 0
    # The trashed run is listed, but the fields come from the last live one.
    assert calls["run_ref"] == "sim-001"
    assert calls["open_zarr"] == "sim-001"
    assert calls["features_for"] == "sim-001"
    assert "Simulation fields (run-one):" in result.stderr
    for name in ("drain", "head", "outflow_drain"):
        assert f"  {name}\n" in result.stderr
    assert "run-two" in result.stderr
    assert calls["closed"] is True


def test_data_export_list_reads_the_run_named_by_sim(monkeypatch, tmp_path) -> None:
    import pandas as pd

    project = tmp_path / "ProjectA"
    project.mkdir()
    catalog_path = catalog_path_for(project)
    catalog_path.parent.mkdir(parents=True, exist_ok=True)
    catalog_path.write_bytes(b"catalog")
    calls: dict[str, object] = {}

    class FakeArray:
        def list_fields(self) -> list[str]:
            return ["head"]

    class FakeRun:
        array = FakeArray()

    class FakeZarr:
        root: dict[str, object] = {}

        def close(self) -> None:
            return None

    class FakeCatalog:
        def __init__(self, root: Path) -> None:
            del root

        def list_simulations(self, *, project: str | None = None):
            del project
            return pd.DataFrame(
                [
                    {
                        "sim_id": "sim-001",
                        "name": "run-one",
                        "solver": "modflow6",
                        "status": "completed",
                        "created_at": "2026-09-16 13:54",
                    }
                ]
            )

        def resolve(self, sim_ref: str, *, project: str | None = None) -> str:
            calls["resolve"] = {"sim_ref": sim_ref, "project": project}
            return "sim-042"

        def open_zarr(self, sim_id: str) -> FakeZarr:
            calls["open_zarr"] = sim_id
            return FakeZarr()

        def __getitem__(self, ref: str) -> FakeRun:
            calls["run_ref"] = ref
            return FakeRun()

        def list_geographic_features(self, sim_id: str) -> list[str]:
            del sim_id
            return []

        def close(self) -> None:
            calls["closed"] = True

    monkeypatch.setattr("hydromodpy.results.catalog.Catalog", FakeCatalog)

    result = CliRunner().invoke(["data", "export", str(project), "--list", "--sim", "run-seven"])

    assert result.exit_code == 0
    assert calls["resolve"] == {"sim_ref": "run-seven", "project": "ProjectA"}
    assert calls["run_ref"] == "sim-042"
    assert calls["open_zarr"] == "sim-042"
    assert "Simulation fields (run-seven):" in result.stderr
    assert calls["closed"] is True
