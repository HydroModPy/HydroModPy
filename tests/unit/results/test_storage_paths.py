"""The runs-first layout: one directory per run, and where each layer of a run lives.

A run directory is ``<project>/runs/<run>``. The resolver finds it from the
``rel_dir`` column of the index.
"""

from __future__ import annotations

import pytest

from hydromodpy.core.state.layout import CATALOG_FILENAME, INTERNAL_DIRNAME, RUNS_DIRNAME
from hydromodpy.results.catalog.storage_paths import StoragePathResolver
from hydromodpy.results.storage.contract import (
    FIELDS_STORE_NAME,
    PARQUET_FILE_SUFFIX,
    PROJECT_STORAGE_LAYER_NAMES,
    RESULT_STORAGE_LAYERS,
    RUN_STORAGE_LAYER_NAMES,
    TABLES_DIRNAME,
)


class _Backend:
    """The one read the resolver makes: ``rel_dir`` of a ``sim_id``."""

    def __init__(self, rows: dict[str, str]) -> None:
        self._rows = rows

    def fetch_one(self, sql: str, params: list):
        assert "rel_dir" in sql
        rel_dir = self._rows.get(params[0])
        return None if rel_dir is None else (rel_dir,)


def test_project_and_run_layers():
    assert PROJECT_STORAGE_LAYER_NAMES == ("catalog",)
    assert RUN_STORAGE_LAYER_NAMES == ("zarr", "parquet")
    assert [layer.name for layer in RESULT_STORAGE_LAYERS] == ["catalog", "zarr", "parquet"]


def test_layer_templates():
    templates = {layer.name: layer.path_template for layer in RESULT_STORAGE_LAYERS}

    assert templates["catalog"] == f"<project>/{INTERNAL_DIRNAME}/{CATALOG_FILENAME}"
    assert templates["zarr"] == f"<project>/{RUNS_DIRNAME}/<run>/{FIELDS_STORE_NAME}"
    assert templates["parquet"] == (
        f"<project>/{RUNS_DIRNAME}/<run>/{TABLES_DIRNAME}/<view>{PARQUET_FILE_SUFFIX}"
    )


def test_resolver_reads_the_directory_of_the_index(tmp_path):
    project = tmp_path / "project"
    run_sid = "00000000-0000-4000-8000-000000000001"
    trial_sid = "00000000-0000-4000-8000-000000000002"
    resolver = StoragePathResolver(
        _Backend({run_sid: "runs/run_one", trial_sid: "sessions/cal/trials/0004"}), project
    )

    run_dir = project / RUNS_DIRNAME / "run_one"
    assert resolver.run_dir_for(run_sid) == run_dir
    assert resolver.fields_path_for(run_sid) == run_dir / FIELDS_STORE_NAME
    assert resolver.tables_dir_for(run_sid) == run_dir / TABLES_DIRNAME
    assert resolver.table_path_for(run_sid, "budget") == (
        run_dir / TABLES_DIRNAME / f"budget{PARQUET_FILE_SUFFIX}"
    )
    assert resolver.run_dir_for(trial_sid) == project / "sessions" / "cal" / "trials" / "0004"
    with pytest.raises(KeyError):
        resolver.run_dir_for("00000000-0000-4000-8000-00000000000f")
