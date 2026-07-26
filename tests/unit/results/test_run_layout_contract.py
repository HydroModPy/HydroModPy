"""Contract of the runs-first output layout.

One solved run must produce exactly one directory, named after the run, and
nothing else anywhere in the project. This is the test that fails loudly if
an output ever regrows an opaque identifier, a container suffix, or a
project-root dumping ground.
"""

from __future__ import annotations

import uuid

import numpy as np
import pandas as pd
import pytest

from hydromodpy.core.state.paths import (
    CATALOG_FILENAME,
    CONFIGS_DIRNAME,
    INTERNAL_DIRNAME,
    PROJECT_MARKER_FILENAME,
    RUNS_DIRNAME,
    SESSIONS_DIRNAME,
    SHARE_DIRNAME,
)
from hydromodpy.results.catalog import Catalog
from hydromodpy.results.manifest import RUN_MANIFEST_FILENAME
from hydromodpy.results.storage.contract import (
    FIELDS_STORE_NAME,
    PARQUET_FILE_SUFFIX,
    RUN_ANNOTATIONS_FILENAME,
    RUN_CONFIG_FILENAME,
    RUN_FIGURES_DIRNAME,
    RUN_LOG_FILENAME,
    RUN_PROVENANCE_FILENAME,
    TABLES_DIRNAME,
)

RUN_NAME = "cheze_baseline"

REQUIRED_RUN_ENTRIES = frozenset({FIELDS_STORE_NAME, TABLES_DIRNAME})
"""What a solved run always leaves behind."""

ALLOWED_RUN_ENTRIES = REQUIRED_RUN_ENTRIES | {
    RUN_CONFIG_FILENAME,
    RUN_PROVENANCE_FILENAME,
    RUN_MANIFEST_FILENAME,
    RUN_ANNOTATIONS_FILENAME,
    RUN_FIGURES_DIRNAME,
    RUN_LOG_FILENAME,
}
"""Every name a run directory may carry: nothing else is a run artefact."""

ALLOWED_PROJECT_ENTRIES = frozenset(
    {
        PROJECT_MARKER_FILENAME,
        CONFIGS_DIRNAME,
        RUNS_DIRNAME,
        SESSIONS_DIRNAME,
        SHARE_DIRNAME,
        INTERNAL_DIRNAME,
    }
)

FORBIDDEN_PROJECT_ENTRIES = (
    "simulations",
    "exports",
    "figures",
    "reports",
    ".solver_scratch",
    "catalog.duckdb",
)

FORBIDDEN_PATH_SUFFIXES = (".parquet.d", ".zarr.zip")


@pytest.fixture
def solved_run(tmp_path):
    """Register, fill and finalize one run; yield ``(project, sim_id)``."""
    project = tmp_path / "project"
    project.mkdir()
    (project / PROJECT_MARKER_FILENAME).write_text("[workspace]\n", encoding="utf-8")
    sim_id = str(uuid.uuid4())

    with Catalog(project) as catalog:
        reg = catalog.register_simulation(
            sim_id,
            project="demo",
            solver="modflow6",
            name=RUN_NAME,
            n_cells=4,
            n_layers=1,
            n_timesteps=3,
            config={"flow": {"k": 1e-5}},
        )
        assert reg.name == RUN_NAME
        if reg.zarr is not None:
            reg.zarr.close()
        catalog.write_parameters(sim_id, [{"param_name": "K", "value": 1e-5}])
        index = pd.date_range("2020-01-01", periods=3, freq="D")
        catalog.write_timeseries(sim_id, "P01", "head", pd.Series(np.ones(3), index=index))
        catalog.write_budget(sim_id, 0, "z1", "recharge", 10.0, 0.0)
        catalog.write_mass_balance(sim_id, 0, 10.0, 9.5, 5.0)
        catalog.write_metric(sim_id, "P01", "nse", 0.8)
        catalog.write_provenance(sim_id, "dem", "dem.tif", np.ones(4))
        catalog.finalize(sim_id, status="completed", duration_s=1.0)

    return project, sim_id


def test_run_writes_one_directory_named_after_the_run(solved_run):
    project, _ = solved_run

    runs_dir = project / RUNS_DIRNAME
    assert [entry.name for entry in sorted(runs_dir.iterdir())] == [RUN_NAME]

    run_dir = runs_dir / RUN_NAME
    entries = {entry.name for entry in run_dir.iterdir()}
    assert REQUIRED_RUN_ENTRIES <= entries
    assert entries <= ALLOWED_RUN_ENTRIES, (
        f"unexpected run artefacts: {entries - ALLOWED_RUN_ENTRIES}"
    )
    assert (run_dir / FIELDS_STORE_NAME).is_dir()
    assert (run_dir / TABLES_DIRNAME).is_dir()


def test_tabular_payloads_are_plain_parquet_files_in_one_directory(solved_run):
    project, _ = solved_run

    tables_dir = project / RUNS_DIRNAME / RUN_NAME / TABLES_DIRNAME
    payloads = sorted(path.name for path in tables_dir.iterdir())

    assert payloads == [
        f"budgets{PARQUET_FILE_SUFFIX}",
        f"mass_balance{PARQUET_FILE_SUFFIX}",
        f"metrics{PARQUET_FILE_SUFFIX}",
        f"parameters{PARQUET_FILE_SUFFIX}",
        f"provenance{PARQUET_FILE_SUFFIX}",
        f"simulation{PARQUET_FILE_SUFFIX}",
        f"timeseries{PARQUET_FILE_SUFFIX}",
    ]
    assert all((tables_dir / name).is_file() for name in payloads)


def test_index_is_the_only_thing_under_the_internal_directory(solved_run):
    project, _ = solved_run

    assert (project / INTERNAL_DIRNAME / CATALOG_FILENAME).is_file()
    assert not (project / CATALOG_FILENAME).exists()


def test_project_root_grows_no_dumping_ground(solved_run):
    project, _ = solved_run

    entries = {entry.name for entry in project.iterdir()}
    assert entries <= ALLOWED_PROJECT_ENTRIES, (
        f"unexpected project-root entries: {entries - ALLOWED_PROJECT_ENTRIES}"
    )
    for forbidden in FORBIDDEN_PROJECT_ENTRIES:
        assert not (project / forbidden).exists(), f"legacy layout entry reappeared: {forbidden}"


def test_no_output_path_carries_an_opaque_identifier(solved_run):
    project, sim_id = solved_run

    short_id = sim_id.replace("-", "")[:8]
    offenders = [
        str(path.relative_to(project))
        for path in project.rglob("*")
        if INTERNAL_DIRNAME not in path.relative_to(project).parts
        and (sim_id in path.name or short_id in path.name)
    ]
    assert offenders == []


def test_no_output_path_carries_a_container_suffix(solved_run):
    project, _ = solved_run

    offenders = [
        str(path.relative_to(project))
        for path in project.rglob("*")
        if str(path).endswith(FORBIDDEN_PATH_SUFFIXES)
    ]
    assert offenders == []


def test_versioned_rerun_is_a_sibling_directory(solved_run):
    project, _ = solved_run

    with Catalog(project) as catalog:
        second = catalog.register_simulation(
            str(uuid.uuid4()),
            project="demo",
            solver="modflow6",
            name=RUN_NAME,
            n_cells=4,
            n_layers=1,
        )
        if second.zarr is not None:
            second.zarr.close()

    assert second.name == f"{RUN_NAME}.v2"
    assert sorted(path.name for path in (project / RUNS_DIRNAME).iterdir()) == [
        RUN_NAME,
        f"{RUN_NAME}.v2",
    ]
