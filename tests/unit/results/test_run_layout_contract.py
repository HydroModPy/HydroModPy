"""Contract of the project and run layout.

A project root holds what its author wrote and seven output roots. A run is
one directory named after the run, holding only the names the storage
contract declares. This test fails loudly if an output regrows an opaque
identifier, a container suffix or a dumping ground at the project root.

The guard is on outputs, not on the author's files: any ``.toml``, ``.csv``
or ``.md`` at the project root belongs to the author and is never flagged.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
import zarr

from hydromodpy.core.budget.terms import BudgetKeep, kept_budget
from hydromodpy.core.state.layout import (
    CATALOG_FILENAME,
    CONFIGS_DIRNAME,
    INTERNAL_DIRNAME,
    JOBS_DIRNAME,
    LAUNCHER_LEASE_FILENAME,
    MESH_CACHE_DIRNAME,
    PLAN_DIRNAME,
    PROJECT_MARKER_FILENAME,
    RUNS_DIRNAME,
    SESSIONS_DIRNAME,
    SITE_OVERRIDES_DIRNAME,
    SUMMARY_DIRNAME,
    TRASH_DIRNAME,
)
from hydromodpy.data.provenance.lockfile import LOCKFILE_NAME
from hydromodpy.mesh.planar.planar_cell_mesh import CellChain
from hydromodpy.results.catalog.constants import PARQUET_VIEW_NAMES
from hydromodpy.results.manifest import MetricRow, read_manifest
from hydromodpy.results.record import sealed_artifacts
from hydromodpy.results.storage.attempt import close_sealed_attempt
from hydromodpy.results.storage.contract import (
    ALLOWED_RUN_ENTRIES,
    FIELDS_STORE_NAME,
    PARQUET_FILE_SUFFIX,
    README_FILENAME,
    REQUIRED_RUN_ENTRIES,
    RUN_INPUTS_FILENAME,
    RUN_LOGS_DIRNAME,
    RUN_OUTCOME_FILENAME,
    RUN_RESOLVED_CONFIG_FILENAME,
    TABLES_DIRNAME,
    UNSEALED_RUN_ENTRIES,
)
from hydromodpy.results.storage.run_store import RunStore
from hydromodpy.results.storage.sealing import IDENTITY_NOTICE_FILENAME, seal_completed
from hydromodpy.workflow.steps.prepare_solver.prepare import step_persist_mesh
from tests._helpers.regular_cell_meshes import regular_cell_mesh
from tests._helpers.run_stores import open_run_store

RUN_NAME = "cheze_baseline"

OUTPUT_ROOTS = frozenset(
    {
        RUNS_DIRNAME,
        SESSIONS_DIRNAME,
        SUMMARY_DIRNAME,
        PLAN_DIRNAME,
        JOBS_DIRNAME,
        TRASH_DIRNAME,
        INTERNAL_DIRNAME,
    }
)
"""The only places a gesture of HydroModPy writes to inside a project."""

AUTHOR_FILE_SUFFIXES = (".toml", ".csv", ".md")
"""A file at the project root with one of these suffixes is the author's."""

ALLOWED_PROJECT_ENTRIES = OUTPUT_ROOTS | frozenset(
    {
        PROJECT_MARKER_FILENAME,
        README_FILENAME,
        CONFIGS_DIRNAME,
        SITE_OVERRIDES_DIRNAME,
        # Pin of the workspace input cache, an input of the project verified by
        # `hmp run --frozen` (hydromodpy/project/launch/lockfile.py).
        LOCKFILE_NAME,
        "sites.csv",
    }
)

FORBIDDEN_PROJECT_ENTRIES = frozenset(
    {
        "share",
        "outputs",
        "catalog.duckdb",
        "simulations",
        "exports",
        "figures",
        "reports",
        ".solver_scratch",
    }
)

PROJECT_LOGS_DIRNAME = "logs"
"""Debug log folder under the project ``.hmp/`` (``hydromodpy/core/logging.py``)."""

REBUILDABLE_INTERNAL_ENTRIES = frozenset(
    {
        CATALOG_FILENAME,
        f"{CATALOG_FILENAME}.wal",
        f"{CATALOG_FILENAME}.lock",
        PROJECT_LOGS_DIRNAME,
        LAUNCHER_LEASE_FILENAME,
        MESH_CACHE_DIRNAME,
        IDENTITY_NOTICE_FILENAME,
    }
)
"""What the project ``.hmp/`` may hold: an index, its companions, a cache, disposable markers."""

FORBIDDEN_PATH_SUFFIXES = (".parquet.d", ".zarr.zip")


def unexpected_project_entries(project: Path) -> set[str]:
    """Return the entries of a project root the layout does not allow.

    A forbidden name is always reported. Any other name is allowed when it is
    declared, or when it is a file the author wrote (``.toml``, ``.csv``,
    ``.md``).
    """
    offenders: set[str] = set()
    for entry in project.iterdir():
        if entry.name in FORBIDDEN_PROJECT_ENTRIES:
            offenders.add(entry.name)
        elif entry.name in ALLOWED_PROJECT_ENTRIES:
            continue
        elif entry.is_file() and entry.suffix in AUTHOR_FILE_SUFFIXES:
            continue
        else:
            offenders.add(entry.name)
    return offenders


@pytest.fixture
def solved_run(tmp_path):
    """Claim, fill and seal one run through its store; yield ``(project, sim_id, author_entries)``.

    The run writes its directory alone and seals itself; the index is derived
    afterwards by the indexer, which this fixture runs the way the launcher
    does once the worker has returned.
    """
    from hydromodpy.results.catalog.indexer import index_new_runs

    project = tmp_path / "project"
    project.mkdir()
    (project / PROJECT_MARKER_FILENAME).write_text("[workspace]\n", encoding="utf-8")
    author_entries = {entry.name for entry in project.iterdir()}

    store = open_run_store(project, RUN_NAME, n_cells=4, n_layers=1, n_timesteps=3)
    sim_id = store.sim_id
    assert store.run_dir.name == RUN_NAME
    (store.run_dir / "config.toml").write_text("[flow]\nk = 1e-5\n", encoding="utf-8")
    (store.run_dir / RUN_LOGS_DIRNAME).mkdir(exist_ok=True)
    store.write_parameters(sim_id, [{"param_name": "K", "value": 1e-5}])
    index = pd.date_range("2020-01-01", periods=3, freq="D")
    store.write_timeseries(sim_id, "P01", "head", pd.Series(np.ones(3), index=index))
    store.write_budget(sim_id, 0, "z1", "recharge", 10.0, 0.0)
    store.write_field_stack(sim_id, "recharge", np.ones((3, 1, 4)), subgroup="budget")
    sz = store.open_zarr(sim_id)
    try:
        sz.write_budget_policy(BudgetKeep.everything(), ["recharge"])
    finally:
        sz.close()
    store.write_mass_balance(sim_id, 0, 10.0, 9.5, 5.0)
    store.write_metric(sim_id, MetricRow(station="P01", metric="nse", value=0.8))
    store.write_provenance(sim_id, "dem", "dem.tif", np.ones(4))
    seal_completed(store)
    close_sealed_attempt(store.run_dir)
    index_new_runs(project)

    return project, sim_id, author_entries


# -- the run directory -------------------------------------------------------


def test_run_writes_one_directory_named_after_the_run(solved_run):
    project, _, _ = solved_run

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


def test_a_completed_run_carries_its_outcome_readme_inputs_and_logs(solved_run):
    project, _, _ = solved_run
    run_dir = project / RUNS_DIRNAME / RUN_NAME

    assert (run_dir / RUN_OUTCOME_FILENAME).is_file()
    assert (run_dir / README_FILENAME).is_file()
    assert (run_dir / RUN_INPUTS_FILENAME).is_file()
    assert (run_dir / RUN_LOGS_DIRNAME).is_dir()


def test_the_whole_configuration_of_a_run_is_a_sealed_entry_of_its_directory(solved_run):
    assert RUN_RESOLVED_CONFIG_FILENAME in ALLOWED_RUN_ENTRIES
    assert RUN_RESOLVED_CONFIG_FILENAME not in UNSEALED_RUN_ENTRIES
    project, _sim_id, _author = solved_run
    run_dir = project / RUNS_DIRNAME / RUN_NAME
    assert RUN_RESOLVED_CONFIG_FILENAME not in {
        artifact["path"] for artifact in read_manifest(run_dir)["artifacts"]
    }, "this store wrote no such file: the seal lists what is there"
    (run_dir / RUN_RESOLVED_CONFIG_FILENAME).write_text("[flow]\n", encoding="utf-8")
    roles = {entry.path: entry.role for entry in sealed_artifacts(run_dir)}
    assert roles[RUN_RESOLVED_CONFIG_FILENAME] == "config_resolved"


def test_a_completed_run_keeps_no_internal_directory(solved_run):
    """The state of the attempt (scratch, locks, checkpoints) is consumed by the seal."""
    project, _, _ = solved_run

    assert not (project / RUNS_DIRNAME / RUN_NAME / INTERNAL_DIRNAME).exists()


def test_the_field_store_and_the_manifest_say_what_budget_the_run_kept(solved_run):
    project, _, _ = solved_run
    run_dir = project / RUNS_DIRNAME / RUN_NAME
    root = zarr.open_group(str(run_dir / FIELDS_STORE_NAME), mode="r")
    kept = kept_budget(root)

    assert kept == ("all", ("recharge",))
    assert read_manifest(run_dir)["budget"] == {"policy": "all", "kept_terms": ["recharge"]}
    # Every derived field is rebuilt on read: the run wrote none.
    assert "derived" not in root


def test_tabular_payloads_are_plain_parquet_files_in_one_directory(solved_run):
    project, _, _ = solved_run

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


# -- the project root --------------------------------------------------------


def test_the_index_lives_under_the_internal_directory(solved_run):
    project, _, _ = solved_run

    assert (project / INTERNAL_DIRNAME / CATALOG_FILENAME).is_file()
    assert not (project / CATALOG_FILENAME).exists()


def test_the_internal_directory_holds_only_rebuildable_entries(solved_run):
    project, _, _ = solved_run

    entries = {entry.name for entry in (project / INTERNAL_DIRNAME).iterdir()}

    assert entries <= REBUILDABLE_INTERNAL_ENTRIES, (
        f"state that is not rebuildable under {INTERNAL_DIRNAME}/: "
        f"{entries - REBUILDABLE_INTERNAL_ENTRIES}"
    )


def test_a_run_writes_nothing_outside_the_output_roots(solved_run):
    project, _, author_entries = solved_run

    written = {entry.name for entry in project.iterdir()} - author_entries

    assert written <= OUTPUT_ROOTS, f"outputs outside the output roots: {written - OUTPUT_ROOTS}"


def test_project_root_grows_no_dumping_ground(solved_run):
    project, _, _ = solved_run

    assert unexpected_project_entries(project) == set()
    for forbidden in FORBIDDEN_PROJECT_ENTRIES:
        assert not (project / forbidden).exists(), f"removed layout entry reappeared: {forbidden}"


def test_author_files_at_the_root_are_never_flagged(tmp_path):
    for name in (
        PROJECT_MARKER_FILENAME,
        README_FILENAME,
        "sites.csv",
        "k2e-5.toml",
        "calage.toml",
        "notes.md",
        "stations.csv",
        LOCKFILE_NAME,
    ):
        (tmp_path / name).write_text("", encoding="utf-8")
    for name in (CONFIGS_DIRNAME, SITE_OVERRIDES_DIRNAME, *OUTPUT_ROOTS):
        (tmp_path / name).mkdir()

    assert unexpected_project_entries(tmp_path) == set()


@pytest.mark.parametrize("name", sorted(FORBIDDEN_PROJECT_ENTRIES))
def test_a_removed_entry_is_flagged(tmp_path, name):
    (tmp_path / name).mkdir()

    assert unexpected_project_entries(tmp_path) == {name}


def test_an_output_file_at_the_root_is_flagged(tmp_path):
    (tmp_path / "heads.nc").write_bytes(b"")
    (tmp_path / "maps").mkdir()

    assert unexpected_project_entries(tmp_path) == {"heads.nc", "maps"}


def test_no_output_path_carries_an_opaque_identifier(solved_run):
    project, sim_id, _ = solved_run

    short_id = sim_id.replace("-", "")[:8]
    offenders = [
        str(path.relative_to(project))
        for path in project.rglob("*")
        if INTERNAL_DIRNAME not in path.relative_to(project).parts
        and (sim_id in path.name or short_id in path.name)
    ]
    assert offenders == []


def test_no_output_path_carries_a_container_suffix(solved_run):
    project, _, _ = solved_run

    offenders = [
        str(path.relative_to(project))
        for path in project.rglob("*")
        if str(path).endswith(FORBIDDEN_PATH_SUFFIXES)
    ]
    assert offenders == []


# -- payloads written after the seal ----------------------------------------


def test_the_soil_budget_is_a_plain_parquet_file_of_the_run(solved_run):
    project, sim_id, _ = solved_run

    assert "soil_budget" in PARQUET_VIEW_NAMES

    with RunStore.open(project / RUNS_DIRNAME / RUN_NAME) as store:
        store.write_view(
            sim_id,
            "soil_budget",
            [
                {
                    "column_id": "0.0",
                    "cell_index": 0,
                    "class_index": 0,
                    "x": 0.0,
                    "y": 0.0,
                    "available_water_capacity": 120.0,
                    "basin_weight": 1.0,
                    "year": 2020,
                    "days": 3,
                    "precipitation": 10.0,
                    "etp": 6.0,
                    "etr": 5.0,
                    "residual_etp": 1.0,
                    "recharge": 4.0,
                    "runoff": 0.0,
                    "soil_storage_change": 1.0,
                    "transit_storage_change": 0.0,
                    "balance_residual": 0.0,
                    "unit": "mm",
                }
            ],
        )

    run_dir = project / RUNS_DIRNAME / RUN_NAME
    assert (run_dir / TABLES_DIRNAME / f"soil_budget{PARQUET_FILE_SUFFIX}").is_file()
    entries = {entry.name for entry in run_dir.iterdir()}
    assert entries <= ALLOWED_RUN_ENTRIES, (
        f"unexpected run artefacts: {entries - ALLOWED_RUN_ENTRIES}"
    )


def test_the_mesh_family_tables_are_plain_parquet_files_of_the_run(tmp_path):
    """The mesh is persisted before the seal, as ``prepare_solver`` does it."""
    project = tmp_path / "project"
    project.mkdir()
    (project / PROJECT_MARKER_FILENAME).write_text("[workspace]\n", encoding="utf-8")
    store = open_run_store(project, RUN_NAME, n_cells=4, n_layers=1, n_timesteps=3)
    sim_id = store.sim_id
    (store.run_dir / "config.toml").write_text("[flow]\nk = 1e-5\n", encoding="utf-8")
    cell_mesh = dataclasses.replace(
        regular_cell_mesh(xmin=0.0, ymin=0.0, dx=10.0, dy=10.0, nrow=2, ncol=2),
        cell_chains=(CellChain(family="rivers", chain_id=0, cell_ids=[2, 0, 1]),),
    )
    ctx = SimpleNamespace(
        setup=SimpleNamespace(
            domain=SimpleNamespace(z_interfaces=np.array([0.0, -10.0])),
            cell_mesh=cell_mesh,
            mesh_summary=None,
        )
    )

    assert {"mesh_cell_families", "mesh_face_families"} <= set(PARQUET_VIEW_NAMES)

    step_persist_mesh(ctx, sim_id, store=store)
    seal_completed(store)
    close_sealed_attempt(store.run_dir)

    run_dir = project / RUNS_DIRNAME / RUN_NAME
    tables_dir = run_dir / TABLES_DIRNAME
    assert (tables_dir / f"mesh_cell_families{PARQUET_FILE_SUFFIX}").is_file()
    # A mesh with no face-intent family writes no face table: nothing to say.
    assert not (tables_dir / f"mesh_face_families{PARQUET_FILE_SUFFIX}").exists()
    chain = pd.read_parquet(tables_dir / f"mesh_cell_families{PARQUET_FILE_SUFFIX}")
    assert chain.sort_values("position")["cell_id"].tolist() == [2, 0, 1]
    assert chain["offset_m"].isna().all()
    assert {entry.name for entry in run_dir.iterdir()} <= ALLOWED_RUN_ENTRIES
    # The seal consolidated the store with the mesh in it.
    mesh_dir = run_dir / FIELDS_STORE_NAME / "mesh"
    assert zarr.open_group(str(mesh_dir), mode="r").attrs["engine"] == "regular"
    assert zarr.open_array(str(mesh_dir / "face_x"), mode="r").shape == (4,)
    # UGRID wants one array per node axis; vertices stays beside them.
    for name in ("node_x", "node_y"):
        assert zarr.open_array(str(mesh_dir / name), mode="r").shape == (9,)
    topology = zarr.open_array(str(mesh_dir / "topology"), mode="r")
    assert topology.attrs["node_coordinates"] == "node_x node_y"
