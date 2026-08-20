"""The runs-first layout: one directory per run, named after the run."""

from __future__ import annotations

import pytest

from hydromodpy.core.state.paths import CATALOG_FILENAME, INTERNAL_DIRNAME, RUNS_DIRNAME
from hydromodpy.results.catalog import Catalog
from hydromodpy.results.catalog.storage_paths import (
    MAX_DIRNAME_LEN,
    RunNameTooLongError,
    run_dirname,
)
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


def test_index_is_project_scoped_and_artefacts_live_in_the_run_directory(tmp_path):
    project = tmp_path / "project"
    sid = "00000000-0000-4000-8000-000000000001"

    with Catalog(project) as catalog:
        assert catalog.catalog_path == project.resolve() / INTERNAL_DIRNAME / CATALOG_FILENAME
        assert catalog.runs_dir == project.resolve() / RUNS_DIRNAME

        reg = catalog.register_simulation(
            sid,
            project="Project A",
            solver="modflow6",
            name="Run One",
            n_cells=1,
            n_layers=1,
        )
        assert reg.zarr is not None
        reg.zarr.close()

        dirname = run_dirname(reg.name)
        run_dir = catalog.runs_dir / dirname

        assert catalog.run_dir_for(sid) == run_dir
        assert catalog.fields_path_for(sid) == run_dir / FIELDS_STORE_NAME
        assert catalog.tables_dir_for(sid) == run_dir / TABLES_DIRNAME

        row = catalog.connection.execute(
            "SELECT zarr_path, storage_basename FROM simulations WHERE sim_id = ?",
            [sid],
        ).fetchone()
        assert row == (
            f"{RUNS_DIRNAME}/{dirname}/{FIELDS_STORE_NAME}",
            dirname,
        )


def test_an_over_long_name_is_refused_instead_of_truncated():
    too_long = "a" * (MAX_DIRNAME_LEN + 1)

    with pytest.raises(RunNameTooLongError) as excinfo:
        run_dirname(too_long)

    assert str(MAX_DIRNAME_LEN) in str(excinfo.value)
    assert run_dirname("a" * MAX_DIRNAME_LEN) == "a" * MAX_DIRNAME_LEN


def test_registration_refuses_two_long_names_sharing_a_prefix(tmp_path):
    """Truncation used to map both names onto one directory: the second died."""
    project = tmp_path / "project"
    stem = "cheze_preretenue_chronicle_" * 4

    with Catalog(project) as catalog:
        for suffix in ("alpha", "beta"):
            with pytest.raises(RunNameTooLongError):
                catalog.register_simulation(
                    "00000000-0000-4000-8000-00000000000" + suffix[0],
                    project="Cheze",
                    solver="modflow6",
                    name=f"{stem}{suffix}",
                    n_cells=1,
                    n_layers=1,
                )
        assert not (catalog.runs_dir).exists() or list(catalog.runs_dir.iterdir()) == []


def test_run_directory_is_named_after_the_run_not_after_an_opaque_id(tmp_path):
    project = tmp_path / "project"
    sid = "00000000-0000-4000-8000-000000000002"

    with Catalog(project) as catalog:
        reg = catalog.register_simulation(
            sid,
            project="Cheze",
            solver="modflow6",
            name="cheze_baseline",
            n_cells=1,
            n_layers=1,
        )
        assert reg.zarr is not None
        reg.zarr.close()

        run_dir = catalog.run_dir_for(sid)

    assert run_dir.name == "cheze_baseline"
    assert sid[:8] not in str(run_dir)
    assert sid not in str(run_dir)
