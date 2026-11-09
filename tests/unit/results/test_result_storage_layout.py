"""The runs-first layout: one directory per run, named after the run."""

from __future__ import annotations

import pytest

from hydromodpy.core.exceptions import ConfigError
from hydromodpy.core.state.layout import CATALOG_FILENAME, INTERNAL_DIRNAME, RUNS_DIRNAME
from hydromodpy.core.state.names import MAX_NAME_LENGTH
from hydromodpy.results.catalog.registration import reserve_version_dirname
from hydromodpy.results.catalog.storage_paths import StoragePathResolver
from hydromodpy.results.storage.contract import (
    FIELDS_STORE_NAME,
    PARQUET_FILE_SUFFIX,
    PROJECT_STORAGE_LAYER_NAMES,
    RESULT_STORAGE_LAYERS,
    RUN_STORAGE_LAYER_NAMES,
    TABLES_DIRNAME,
)


def test_storage_layers_make_project_vs_run_scope_explicit():
    assert PROJECT_STORAGE_LAYER_NAMES == ("catalog",)
    assert RUN_STORAGE_LAYER_NAMES == ("zarr", "parquet")
    assert [layer.name for layer in RESULT_STORAGE_LAYERS] == [
        "catalog",
        "zarr",
        "parquet",
    ]


def test_storage_layer_templates_describe_the_runs_first_tree():
    templates = {layer.name: layer.path_template for layer in RESULT_STORAGE_LAYERS}

    assert templates["catalog"] == f"<project>/{INTERNAL_DIRNAME}/{CATALOG_FILENAME}"
    assert templates["zarr"] == f"<project>/{RUNS_DIRNAME}/<run>/{FIELDS_STORE_NAME}"
    assert templates["parquet"] == (
        f"<project>/{RUNS_DIRNAME}/<run>/{TABLES_DIRNAME}/<view>{PARQUET_FILE_SUFFIX}"
    )


class _Backend:
    """The one read the resolver makes: ``rel_dir`` of a ``sim_id``."""

    def __init__(self, rows: dict[str, str]) -> None:
        self._rows = rows

    def fetch_one(self, sql: str, params: list):
        assert "rel_dir" in sql
        rel_dir = self._rows.get(params[0])
        return None if rel_dir is None else (rel_dir,)


def test_the_resolver_reads_the_relative_directory_of_the_index(tmp_path):
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


def test_an_over_long_name_is_refused_instead_of_truncated(tmp_path):
    too_long = "a" * (MAX_NAME_LENGTH + 1)

    with pytest.raises(ConfigError, match=str(MAX_NAME_LENGTH)):
        reserve_version_dirname(tmp_path / "project", "run", too_long)

    kept = reserve_version_dirname(tmp_path / "project", "run", "a" * MAX_NAME_LENGTH)
    assert kept.name == "a" * MAX_NAME_LENGTH


def test_a_reservation_refuses_two_long_names_sharing_a_prefix(tmp_path):
    """Truncation used to map both names onto one directory: the second died."""
    project = tmp_path / "project"
    stem = "cheze_preretenue_chronicle_" * 2

    for suffix in ("alpha", "beta"):
        with pytest.raises(ConfigError):
            reserve_version_dirname(project, "run", f"{stem}{suffix}")
    assert not (project / RUNS_DIRNAME).exists() or list((project / RUNS_DIRNAME).iterdir()) == []


def test_run_directory_is_named_after_the_run_not_after_an_opaque_id(tmp_path):
    run_dir = reserve_version_dirname(tmp_path / "project", "run", "cheze_baseline")
    assert run_dir == tmp_path / "project" / RUNS_DIRNAME / "cheze_baseline"
