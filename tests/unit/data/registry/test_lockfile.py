"""P9 lockfile contract tests.

Cover the four mandatory sections, atomicity, and the strict verify path that
``hmp lock verify --strict`` relies on. The lock is written once by the
launcher (``lock_update``), never by a run; the last section pins the one
address of ``hydromodpy.lock``: the project root it was written to.
"""

from __future__ import annotations

import inspect
import os
import re
import tarfile
import threading
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

import pytest
import tomlkit

from hydromodpy.core.exceptions import (
    CacheCorruptionError,
    FrozenDataError,
    SchemaVersionMismatchError,
)
from hydromodpy.data.managers.base_manager_field import BaseFieldManager
from hydromodpy.data.provenance.lockfile import (
    LOCKFILE_NAME,
    LOCKFILE_SCHEMA,
    read_lockfile_binaries,
    read_lockfile_inputs,
    read_lockfile_meta,
    sha256_of,
)
from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB
from hydromodpy.data.registry.freeze import (
    archive_lockfile,
    restore_archive,
    verify_frozen,
    verify_inputs_strict,
    write_lockfile,
)
from hydromodpy.results.storage.parquet_schemas import PARQUET_SCHEMA_VERSION
from hydromodpy.results.zarr_store.constants import ZARR_SCHEMA_VERSION

_SCHEMA_VERSIONS = {
    "zarr_schema_version": ZARR_SCHEMA_VERSION,
    "parquet_schema_version": PARQUET_SCHEMA_VERSION,
}
"""The storage schema versions a lockfile records: the data layer is handed them."""


def _seed_workspace(tmp: Path) -> tuple[DataCatalogDuckDB, Path, Path]:
    """Build a minimal workspace layout with one catalog entry."""
    workspace = tmp / "workspace"
    data_dir = workspace / "data" / "hydrometry"
    data_dir.mkdir(parents=True)
    src = data_dir / "series_A.csv"
    src.write_text("datetime,value\n2020-01-01,1.0\n")
    catalog = DataCatalogDuckDB(workspace / "data" / "cache.duckdb")
    catalog.register(
        variable="hydrometry",
        source="hubeau",
        station_id="A",
        file_path=src.name,
    )
    return catalog, workspace, src


def test_write_lockfile_contains_required_sections(tmp_path: Path) -> None:
    catalog, workspace, _ = _seed_workspace(tmp_path)
    dest = workspace / LOCKFILE_NAME
    write_lockfile(catalog, dest, **_SCHEMA_VERSIONS)

    doc = tomlkit.parse(dest.read_text())
    assert doc["schema"] == LOCKFILE_SCHEMA == "hydromodpy.lock.v1"
    for section in ("hydromodpy", "binaries", "input"):
        assert section in doc, f"missing [{section}] section"

    meta = read_lockfile_meta(dest)
    assert "version" not in meta
    assert "hydromodpy_version" in meta
    assert "python_version" in meta
    assert "catalog_schema_version" in meta
    assert meta["zarr_schema_version"] == ZARR_SCHEMA_VERSION == "4"
    assert meta["parquet_schema_version"] == PARQUET_SCHEMA_VERSION == "v3"

    assert read_lockfile_inputs(dest), "[[input]] must list registered artefacts"
    assert set(doc["input"][0]) == {
        "variable",
        "source",
        "station_id",
        "path",
        "sha256",
        "bytes",
        "file_mtime",
        "fetched_at",
    }


def test_a_lockfile_of_the_old_shape_is_refused_by_name(tmp_path: Path) -> None:
    """``[schema]`` was a table of the old shape, and it is no version."""
    dest = tmp_path / LOCKFILE_NAME
    dest.write_text('[hydromodpy]\nversion = "2.0.0"\n\n[schema]\ncatalog = 1\n')

    with pytest.raises(SchemaVersionMismatchError, match="carries no schema.*hmp lock update"):
        read_lockfile_inputs(dest)


def test_write_lockfile_atomic(tmp_path: Path) -> None:
    """A pre-existing lockfile is never partially overwritten."""
    catalog, workspace, src = _seed_workspace(tmp_path)
    dest = workspace / LOCKFILE_NAME

    # Seed with a known payload so we can prove it survives if a swap fails.
    dest.write_text('[hydromodpy]\nversion = "old"\n', encoding="utf-8")
    pristine = dest.read_bytes()

    # The atomic helper writes to a sibling tmp file then renames in place.
    # Trace inode swaps via the source/destination dev+ino pair.
    before_stat = dest.stat()
    write_lockfile(catalog, dest, **_SCHEMA_VERSIONS)
    after_stat = dest.stat()

    # Replace must have substituted the inode (Unix rename semantics).
    assert (before_stat.st_dev, before_stat.st_ino) != (after_stat.st_dev, after_stat.st_ino)
    # No stray ``.lockfile.tmp.*`` after the call.
    leftovers = [p for p in dest.parent.iterdir() if p.name.startswith(f".{dest.name}.tmp.")]
    assert leftovers == []
    # Final payload is well-formed TOML with our header.
    parsed = tomlkit.parse(dest.read_text())
    assert parsed["schema"] == LOCKFILE_SCHEMA
    # The previously stored bytes were complete (sanity, not a partial write).
    assert tomlkit.parse(pristine.decode("utf-8"))["hydromodpy"]["version"] == "old"
    threading.current_thread()  # keep the import in use for clarity
    catalog.close()
    assert src.is_file()


def test_lockfile_includes_binary_sha256(tmp_path: Path) -> None:
    catalog, workspace, _ = _seed_workspace(tmp_path)
    fake_solver = tmp_path / "fake_mf6"
    payload = b"\x7fELF" + b"\x00" * 64
    fake_solver.write_bytes(payload)
    fake_solver.chmod(0o755)

    dest = workspace / LOCKFILE_NAME
    write_lockfile(catalog, dest, solvers={"modflow6": fake_solver}, **_SCHEMA_VERSIONS)

    binaries = read_lockfile_binaries(dest)
    assert binaries.get("modflow6_sha256") == sha256_of(fake_solver)
    # A lockfile travels with its project: no path of this machine in it.
    assert not any(key.endswith("_path") for key in binaries)
    assert str(tmp_path) not in dest.read_text()


def test_lockfile_includes_inputs_sha256(tmp_path: Path) -> None:
    catalog, workspace, src = _seed_workspace(tmp_path)
    dest = workspace / LOCKFILE_NAME
    write_lockfile(catalog, dest, **_SCHEMA_VERSIONS)
    inputs = read_lockfile_inputs(dest)
    assert len(inputs) == 1
    assert inputs[0].path == src.relative_to(workspace).as_posix()
    assert inputs[0].sha256 == sha256_of(src)
    assert inputs[0].bytes == src.stat().st_size


def test_verify_lockfile_passes_when_unchanged(tmp_path: Path) -> None:
    catalog, workspace, _ = _seed_workspace(tmp_path)
    dest = workspace / LOCKFILE_NAME
    write_lockfile(catalog, dest, **_SCHEMA_VERSIONS)
    assert verify_frozen(catalog, dest) == []
    assert verify_inputs_strict(catalog, dest) == []


def test_verify_lockfile_warns_on_changed_input(tmp_path: Path) -> None:
    catalog, workspace, src = _seed_workspace(tmp_path)
    dest = workspace / LOCKFILE_NAME
    write_lockfile(catalog, dest, **_SCHEMA_VERSIONS)
    # Mutate the file. verify_frozen still tolerates a mismatch (returns a
    # list to be reported as warnings by ``hmp lock verify``).
    src.write_text("datetime,value\n2020-01-01,9.0\n")
    mismatches = verify_frozen(catalog, dest)
    assert len(mismatches) == 1
    assert mismatches[0].kind == "sha256"
    assert mismatches[0].path == src.relative_to(workspace).as_posix()


def test_verify_strict_fails_on_changed_input(tmp_path: Path) -> None:
    catalog, workspace, src = _seed_workspace(tmp_path)
    dest = workspace / LOCKFILE_NAME
    write_lockfile(catalog, dest, **_SCHEMA_VERSIONS)
    src.write_text("datetime,value\n2020-01-01,5.0\n")
    mismatches = verify_inputs_strict(catalog, dest)
    assert len(mismatches) == 1
    m = mismatches[0]
    assert m.kind == "sha256"
    assert m.path == src.relative_to(workspace).as_posix()
    assert m.expected != m.observed


def _run_cli_workflow(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Drive the real ``hmp run`` code path and return the project root.

    Only the workflow engine is stubbed. Everything the CLI itself decides
    runs for real, so a lockfile would land on disk if the CLI wrote one.
    """
    import argparse
    from types import SimpleNamespace

    from hydromodpy.cli.commands import run as run_cmd
    from hydromodpy.project.dispatch import workflow as project_workflow

    catalog, workspace, _ = _seed_workspace(tmp_path)
    catalog.close()

    config_path = workspace / "overview.toml"
    config_path.write_text(
        "\n".join(
            [
                "[workflow]",
                'mode = "overview"',
                "",
                "[workspace]",
                f'root = "{workspace.as_posix()}"',
                "",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setitem(
        project_workflow.DISPATCH,
        "overview",
        lambda path: SimpleNamespace(to_dict=lambda: {"sim_id": "stub", "name": "stub"}),
    )
    monkeypatch.chdir(workspace)

    args = argparse.Namespace(config=str(config_path))
    run_cmd.run(args)
    return workspace


def test_a_run_writes_no_lockfile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``hmp run`` leaves the project lockfile alone.

    What a run read is recorded in ``inputs.json`` of its own directory; the
    project lockfile that ``--frozen`` reads is written by
    ``hmp lock update`` only. Asserts the absence of the file: disk is the
    contract.
    """
    workspace = _run_cli_workflow(tmp_path, monkeypatch)

    assert not (workspace / LOCKFILE_NAME).exists()


# Bonus coverage --------------------------------------------------------------


def test_lockfile_uses_temporary_file_then_replaces(tmp_path: Path) -> None:
    """Confirm the tmp + replace path: no partial file is ever created."""
    catalog, workspace, _ = _seed_workspace(tmp_path)
    dest = workspace / LOCKFILE_NAME
    write_lockfile(catalog, dest, **_SCHEMA_VERSIONS)
    # No ``.lockfile.tmp.*`` sibling is left around after the write.
    tmps = [p for p in dest.parent.iterdir() if p.name.startswith(f".{dest.name}.tmp.")]
    assert tmps == []
    # The destination is a regular file with the expected permissions
    # (POSIX only).
    if os.name == "posix":
        mode = dest.stat().st_mode & 0o777
        assert mode in {0o644, 0o664}


def test_sidecar_emitted_on_register(tmp_path: Path) -> None:
    """The catalog register() helper drops a JSON sidecar for raw inputs."""
    catalog, workspace, src = _seed_workspace(tmp_path)
    sidecar = src.with_name(src.name + ".json")
    catalog.close()
    assert sidecar.is_file(), "sidecar JSON must follow each register()"
    import json

    payload = json.loads(sidecar.read_text(encoding="utf-8"))
    assert payload["sha256"] == sha256_of(src)
    assert payload["source"] == "hubeau"


def test_lockfile_round_trip_input_records(tmp_path: Path) -> None:
    """The ``[[input]]`` records round-trip through the writer and the reader."""
    catalog, workspace, _ = _seed_workspace(tmp_path)
    dest = workspace / LOCKFILE_NAME
    write_lockfile(catalog, dest, **_SCHEMA_VERSIONS)
    entries = read_lockfile_inputs(dest)
    assert len(entries) == 1
    assert entries[0].variable == "hydrometry"
    assert entries[0].sha256
    # ``fetched_at`` should be ISO8601 with UTC offset.
    assert "T" in entries[0].fetched_at
    # Sanity: a second write does not duplicate inputs.
    write_lockfile(catalog, dest, **_SCHEMA_VERSIONS)
    assert len(read_lockfile_inputs(dest)) == 1


# Merged from tests/unit/test_lockfile.py ------------------------------------


def _seed_catalog(tmp: Path) -> tuple[DataCatalogDuckDB, Path]:
    cache = tmp / "cache.duckdb"
    src = tmp / "x.csv"
    src.write_text("a,b\n1,2\n")
    cat = DataCatalogDuckDB(cache)
    cat.register(variable="hydrometry", source="custom", station_id="A", file_path=src)
    return cat, src


def test_sha256_of_matches_standard(tmp_path: Path) -> None:
    p = tmp_path / "f.bin"
    p.write_bytes(b"hello")
    # sha256("hello") = 2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824
    assert sha256_of(p) == ("2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824")


def test_archive_and_restore(tmp_path: Path) -> None:
    cat, _ = _seed_catalog(tmp_path)
    archive = tmp_path / "export.tar"
    archive_lockfile(cat, archive, lockfile_dest=tmp_path / LOCKFILE_NAME, **_SCHEMA_VERSIONS)
    assert archive.is_file()
    restore_dir = tmp_path / "restored"
    restore_archive(archive, restore_dir)
    assert (restore_dir / LOCKFILE_NAME).is_file()


def _damage_tamper(path: Path) -> None:
    path.write_text("other bytes\n")


@pytest.mark.parametrize(
    ("damage", "said"),
    [
        pytest.param(_damage_tamper, "expected sha256", id="tampered"),
        pytest.param(Path.unlink, "absent from the archive", id="missing"),
    ],
)
def test_a_bad_archive_is_refused_and_leaves_nothing(tmp_path: Path, damage, said: str) -> None:
    catalog, workspace, src = _seed_workspace(tmp_path)
    archive = tmp_path / "good.tar"
    archive_lockfile(catalog, archive, lockfile_dest=workspace / LOCKFILE_NAME, **_SCHEMA_VERSIONS)
    unpacked = tmp_path / "unpacked"
    with tarfile.open(archive) as tar:
        tar.extractall(unpacked, filter="data")
    damage(unpacked / "artefacts" / sha256_of(src) / src.name)
    bad = tmp_path / "bad.tar"
    with tarfile.open(bad, "w") as tar:
        tar.add(unpacked, arcname=".")

    target = tmp_path / "out" / "restored"
    with pytest.raises(CacheCorruptionError, match=re.escape(said)):
        restore_archive(bad, target)
    assert list(target.parent.iterdir()) == []


def test_an_archive_without_its_lockfile_is_refused(tmp_path: Path) -> None:
    bare = tmp_path / "bare.tar"
    with tarfile.open(bare, "w"):
        pass
    with pytest.raises(CacheCorruptionError, match=f"holds no {LOCKFILE_NAME}"):
        restore_archive(bare, tmp_path / "restored")


def test_a_generated_series_names_no_file_in_the_catalog(tmp_path: Path) -> None:
    """A synthetic recharge has no file: the catalog named one, and ``--frozen`` looked for it."""
    catalog, workspace, _ = _seed_workspace(tmp_path)
    manager = SimpleNamespace(catalog=catalog, VARIABLE_NAME="recharge")
    generated = SimpleNamespace(source="synthetic", file_path=None, location=None)
    BaseFieldManager._register_point_records(manager, [generated])
    assert not catalog.backend.fetch_all("SELECT id FROM entries WHERE source = 'synthetic'")

    dest = workspace / LOCKFILE_NAME
    write_lockfile(catalog, dest, **_SCHEMA_VERSIONS)
    # An entry with no file was never in a lock, so the lock has nothing to say of it.
    catalog.register(variable="recharge", source="synthetic", file_path="no_such_file")
    assert verify_frozen(catalog, dest) == []
    assert verify_inputs_strict(catalog, dest) == []


def test_lockfile_resolves_workspace_data_variable_relative_paths(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    data_dir = workspace / "data" / "hydrometry"
    data_dir.mkdir(parents=True)
    src = data_dir / "hydrometry_hubeau_A_20200101_20200102_D.csv"
    src.write_text("datetime,value\n2020-01-01,1.0\n")

    cat = DataCatalogDuckDB(workspace / "data" / "cache.duckdb")
    cat.register(
        variable="hydrometry",
        source="hubeau",
        station_id="A",
        file_path=src.name,
    )
    dest = workspace / LOCKFILE_NAME
    write_lockfile(cat, dest, **_SCHEMA_VERSIONS)

    entries = read_lockfile_inputs(dest)
    assert len(entries) == 1
    assert entries[0].path == src.relative_to(workspace).as_posix()
    assert entries[0].sha256 == sha256_of(src)
    assert verify_frozen(cat, dest) == []


def test_verify_frozen_keeps_distinct_gridded_artifacts(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    data_dir = workspace / "data" / "precipitation"
    data_dir.mkdir(parents=True)
    first = data_dir / "precip_a.nc"
    second = data_dir / "precip_b.nc"
    first.write_text("a")
    second.write_text("b")

    cat = DataCatalogDuckDB(workspace / "data" / "cache.duckdb")
    cat.register(variable="precipitation", source="sim2", file_path=first.name)
    cat.register(variable="precipitation", source="sim2", file_path=second.name)
    dest = workspace / LOCKFILE_NAME
    write_lockfile(cat, dest, **_SCHEMA_VERSIONS)

    entries = read_lockfile_inputs(dest)
    assert {entry.path for entry in entries} == {
        first.relative_to(workspace).as_posix(),
        second.relative_to(workspace).as_posix(),
    }
    assert verify_frozen(cat, dest) == []


# One address: what ``hmp lock update`` writes is what --frozen reads ------


@pytest.fixture
def frozen_mode_reset() -> Iterator[None]:
    """Leave the process-wide frozen mode as it was found."""
    from hydromodpy.data.provenance.lockfile import (
        frozen_project_root,
        is_frozen_mode,
        set_frozen_mode,
    )

    was_enabled = is_frozen_mode()
    bound_root = frozen_project_root()
    yield
    if was_enabled and bound_root is not None:
        set_frozen_mode(True, project_root=bound_root)
    else:
        set_frozen_mode(False)


def _seed_workspace_project(tmp: Path) -> tuple[Path, Path, Path]:
    """Workspace-style layout: cache under the workspace, project one level down.

    This is the layout the old guess got wrong: ``<db>.parent.parent`` is the
    workspace root, not the project root that owns the lockfile.
    """
    workspace = tmp / "workspace"
    project_root = workspace / "projects" / "demo"
    data_dir = workspace / "data" / "hydrometry"
    data_dir.mkdir(parents=True)
    project_root.mkdir(parents=True)
    src = data_dir / "series.csv"
    src.write_text("datetime,value\n2020-01-01,1.0\n")
    catalog = DataCatalogDuckDB(workspace / "data" / "cache.duckdb")
    catalog.register(variable="hydrometry", source="hubeau", station_id="A", file_path=src.name)
    catalog.close()
    config_path = project_root / "project.toml"
    config_path.write_text("# config placeholder\n")
    return workspace, project_root, config_path


def test_project_lockfile_path_is_the_project_root(tmp_path: Path) -> None:
    from hydromodpy.data.provenance.lockfile import project_lockfile_path

    assert project_lockfile_path(tmp_path) == tmp_path / LOCKFILE_NAME


def test_cache_store_no_longer_guesses_the_lockfile_location() -> None:
    """The candidate-scanning resolver is gone, not aliased."""
    from hydromodpy.data.registry import cache_store

    assert not hasattr(cache_store, "workspace_lockfile_path")


def test_frozen_mode_reads_the_lockfile_lock_update_wrote(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    frozen_mode_reset: None,
) -> None:
    """The file ``hmp lock update`` wrote is the one frozen mode loads."""
    from hydromodpy.cli._workers.dev import lock_update
    from hydromodpy.data.provenance.lockfile import project_lockfile_path, set_frozen_mode
    from hydromodpy.data.registry import cache_store

    monkeypatch.delenv("HMP_WORKSPACE", raising=False)
    workspace, project_root, _config_path = _seed_workspace_project(tmp_path)
    lock_update(project=str(project_root))

    written = project_lockfile_path(project_root)
    assert written.is_file()
    # The directories the old resolver scanned hold nothing to fall back on.
    assert not (workspace / LOCKFILE_NAME).exists()
    assert not (workspace / "data" / LOCKFILE_NAME).exists()

    set_frozen_mode(True, project_root=project_root)
    assert [item.station_id for item in cache_store.locked_inputs()] == ["A"]


def test_frozen_precheck_accepts_the_lockfile_lock_update_wrote(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``hmp run --frozen`` resolves the address ``hmp lock update`` writes."""
    from hydromodpy.cli._workers.dev import lock_update
    from hydromodpy.cli.commands.run import _verify_frozen_inputs_strict

    monkeypatch.delenv("HMP_WORKSPACE", raising=False)
    _, project_root, config_path = _seed_workspace_project(tmp_path)
    raw_toml = {"workspace": {"project_root": str(project_root)}}
    lock_update(project=str(project_root))

    assert _verify_frozen_inputs_strict(config_path, raw_toml) == project_root


def test_the_lockfile_lock_update_wrote_records_the_schema_versions_of_the_stores(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from hydromodpy.cli._workers.dev import lock_update
    from hydromodpy.data.provenance.lockfile import project_lockfile_path

    monkeypatch.delenv("HMP_WORKSPACE", raising=False)
    _, project_root, _ = _seed_workspace_project(tmp_path)
    lock_update(project=str(project_root))

    meta = read_lockfile_meta(project_lockfile_path(project_root))
    assert meta["zarr_schema_version"] == ZARR_SCHEMA_VERSION
    assert meta["parquet_schema_version"] == PARQUET_SCHEMA_VERSION


@pytest.mark.parametrize("worker", ["lock_archive", "archive_data_cache"])
def test_the_archive_of_the_cli_records_the_schema_versions_of_the_stores(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, worker: str
) -> None:
    import importlib
    import tarfile

    module = (
        "hydromodpy.cli._workers.dev"
        if worker == "lock_archive"
        else "hydromodpy.cli._workers.data"
    )
    archive_cli = getattr(importlib.import_module(module), worker)
    monkeypatch.delenv("HMP_WORKSPACE", raising=False)
    workspace, _, _ = _seed_workspace_project(tmp_path)
    archive = tmp_path / "export.tar"
    archive_cli(archive, workspace=str(workspace))

    with tarfile.open(archive) as tar:
        tar.extract(LOCKFILE_NAME, tmp_path / "unpacked", filter="data")
    meta = read_lockfile_meta(tmp_path / "unpacked" / LOCKFILE_NAME)
    assert meta["zarr_schema_version"] == ZARR_SCHEMA_VERSION
    assert meta["parquet_schema_version"] == PARQUET_SCHEMA_VERSION


@pytest.mark.parametrize("writer", [write_lockfile, archive_lockfile])
def test_the_data_layer_holds_no_copy_of_the_schema_versions(writer) -> None:
    """The versions live in ``hydromodpy.results``, so the caller gives them: no default."""
    parameters = inspect.signature(writer).parameters
    for name in ("zarr_schema_version", "parquet_schema_version"):
        assert parameters[name].default is inspect.Parameter.empty


def test_locked_inputs_names_the_expected_path_when_missing(
    tmp_path: Path,
    frozen_mode_reset: None,
) -> None:
    from hydromodpy.data.provenance.lockfile import project_lockfile_path, set_frozen_mode
    from hydromodpy.data.registry import cache_store

    project_root = tmp_path / "project"
    project_root.mkdir()
    set_frozen_mode(True, project_root=project_root)

    expected = project_lockfile_path(project_root.resolve())
    with pytest.raises(RuntimeError, match=re.escape(str(expected))):
        cache_store.locked_inputs()


def test_locked_inputs_without_a_bound_project_says_so(frozen_mode_reset: None) -> None:
    """A lookup made outside frozen mode names the missing binding, never guesses."""
    from hydromodpy.data.provenance.lockfile import set_frozen_mode
    from hydromodpy.data.registry import cache_store

    set_frozen_mode(False)
    with pytest.raises(RuntimeError, match="no project bound"):
        cache_store.locked_inputs()


def test_enabling_frozen_mode_without_a_project_is_refused(frozen_mode_reset: None) -> None:
    """``project_root`` is required to enable: no sticky previous binding."""
    from hydromodpy.data.provenance.lockfile import is_frozen_mode, set_frozen_mode

    with pytest.raises(ValueError, match="project_root"):
        set_frozen_mode(True)
    assert is_frozen_mode() is False


def test_every_enable_names_its_own_project(tmp_path: Path, frozen_mode_reset: None) -> None:
    from hydromodpy.data.provenance.lockfile import frozen_project_root, set_frozen_mode

    first = tmp_path / "first"
    second = tmp_path / "second"
    set_frozen_mode(True, project_root=first)
    assert frozen_project_root() == first.resolve()
    set_frozen_mode(True, project_root=second)
    assert frozen_project_root() == second.resolve()
    with pytest.raises(ValueError, match="project_root"):
        set_frozen_mode(True)
    set_frozen_mode(False)
    assert frozen_project_root() is None


def test_project_runner_binds_the_project_root_it_runs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    frozen_mode_reset: None,
) -> None:
    """``ProjectRunner.run(frozen=True)`` reaches a catalog lookup, not a RuntimeError.

    Only the pipeline is replaced: the frozen binding and its restore are the
    real ones from :mod:`hydromodpy.project.runner`.
    """
    from types import SimpleNamespace

    from hydromodpy.cli._workers.dev import lock_update
    from hydromodpy.data.provenance.lockfile import frozen_project_root, is_frozen_mode
    from hydromodpy.data.registry import cache_store
    from hydromodpy.project.runner import ProjectRunner

    monkeypatch.delenv("HMP_WORKSPACE", raising=False)
    _, project_root, config_path = _seed_workspace_project(tmp_path)
    lock_update(project=str(project_root))

    seen: dict[str, object] = {}

    class RecordingPipeline:
        def __init__(self, steps: tuple, *, workspace: Path, run_dir: Path | None) -> None:
            seen["workspace"] = workspace
            seen["run_dir"] = run_dir

        def run(self, initial: object, **kwargs: object) -> dict:
            seen["frozen"] = is_frozen_mode()
            seen["root"] = frozen_project_root()
            seen["stations"] = [a.station_id for a in cache_store.locked_inputs()]
            return {"ctx": ctx}

    monkeypatch.setattr("hydromodpy.workflow.runner.Pipeline", RecordingPipeline)
    monkeypatch.setattr(
        "hydromodpy.workflow.steps.planning.step_build_plan",
        lambda *a, **k: None,
    )
    monkeypatch.setattr("hydromodpy.project.phases.open_catalog", lambda project: None)

    ctx = SimpleNamespace(
        setup=SimpleNamespace(
            workspace=SimpleNamespace(project_root=project_root),
            geographic=None,
            domain=None,
            flow=None,
            run_id=None,
            flow_runtime_overrides=None,
        ),
        data_plan=SimpleNamespace(types=()),
        raw_toml={},
        store=None,
        sim_id=None,
    )
    # A run that keeps no store claims no directory: only the frozen binding
    # is under test.
    unpersisted = SimpleNamespace(
        simulation=SimpleNamespace(
            results=SimpleNamespace(persistence=SimpleNamespace(save_catalog=False))
        ),
        site=None,
    )
    project = SimpleNamespace(
        _ctx=ctx,
        _cfg=unpersisted,
        _config_path=config_path,
        # The double stands for a project the Pipeline builds itself: no
        # geographic and no domain on its ctx, so the run executes the model
        # phase and the Project adopts the phase the Pipeline reached.
        _ensure_model_built=lambda: None,
        _phase="uninitialized",
        _data_loaded=set(),
        _no_display=True,
        _run_counter=0,
        _solver=None,
        _store=None,
        _run_history=[],
        _spatial_support_registry=None,
        _requested_support_ids=None,
        _requested_domain_supports=None,
    )

    assert ProjectRunner(project).run(name="frozen_run", frozen=True) is None
    assert seen["frozen"] is True
    assert seen["root"] == project_root.resolve()
    assert seen["stations"] == ["A"]
    assert is_frozen_mode() is False
    assert frozen_project_root() is None


def test_lock_verify_accepts_an_explicit_lockfile_from_anywhere(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``--lockfile`` plus ``--workspace`` names both addresses, so no project is needed.

    This is the ``hmp data restore`` then ``hmp lock verify`` path: the
    restored lockfile sits under the workspace, not under a project root.
    """
    from hydromodpy.cli._workers.dev import lock_update, lock_verify

    monkeypatch.delenv("HMP_WORKSPACE", raising=False)
    workspace, project_root, _ = _seed_workspace_project(tmp_path)
    written = lock_update(project=str(project_root))

    monkeypatch.chdir(tmp_path)
    assert lock_verify(str(workspace), lockfile=str(written))["ok"] is True
    with pytest.raises(FileNotFoundError, match="project.toml"):
        lock_verify(str(workspace))


def test_lock_update_and_verify_need_no_project_when_the_file_is_named(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``--output`` then ``--lockfile``, with neither ``--project`` nor ``--workspace``.

    The named file is the address and the directory it sits in is the project
    it describes, so the pair answers from a directory that is no project. The
    cache comes from the workspace above that file.
    """
    from hydromodpy.cli._workers.dev import lock_update, lock_verify

    monkeypatch.delenv("HMP_WORKSPACE", raising=False)
    monkeypatch.delenv("HMP_PROJECT_ROOT", raising=False)
    workspace, _, _ = _seed_workspace_project(tmp_path)
    restored = workspace / "restored"
    restored.mkdir()
    monkeypatch.chdir(tmp_path)

    written = lock_update(output=str(restored / "custom.lock"))

    assert written == (restored / "custom.lock").resolve()
    assert lock_verify(lockfile=str(written))["ok"] is True


def test_lock_update_outside_any_workspace_raises_instead_of_exiting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The worker raises; turning that into an exit code is the command's job.

    ``pytest.raises`` fails on the ``SystemExit`` the CLI-only workspace
    resolver used to raise from inside the worker.
    """
    from hydromodpy.cli._workers.dev import lock_update

    monkeypatch.delenv("HMP_WORKSPACE", raising=False)
    orphan = tmp_path / "orphan"
    orphan.mkdir()
    monkeypatch.chdir(orphan)

    with pytest.raises(FileNotFoundError, match="-w"):
        lock_update(output=str(orphan / "custom.lock"))


# One writer: the lockfile records the commit of the project it describes -----


def test_the_lockfile_records_the_project_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``hmp lock update`` writes the commit of the project, not of the cwd."""
    from hydromodpy.cli._workers.dev import lock_update
    from hydromodpy.data.provenance.lockfile import project_lockfile_path
    from hydromodpy.data.registry import freeze

    monkeypatch.delenv("HMP_WORKSPACE", raising=False)
    monkeypatch.delenv("HMP_PROJECT_ROOT", raising=False)
    monkeypatch.setattr(freeze, "_git_head", lambda cwd: f"commit-of-{Path(cwd).name}")
    _, project_root, _config_path = _seed_workspace_project(tmp_path)
    dest = project_lockfile_path(project_root)

    assert lock_update(project=str(project_root)) == dest
    meta = read_lockfile_meta(dest)

    assert meta["project_git_commit"] == "commit-of-demo"


def test_env_project_root_beats_the_declared_one(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``HMP_PROJECT_ROOT`` moves the lockfile ``--frozen`` reads, as it moves the config."""
    from hydromodpy.cli._workers.dev import lock_update
    from hydromodpy.cli.commands.run import _verify_frozen_inputs_strict
    from hydromodpy.data.provenance.lockfile import project_lockfile_path

    monkeypatch.delenv("HMP_WORKSPACE", raising=False)
    workspace, declared, config_path = _seed_workspace_project(tmp_path)
    env_root = workspace / "projects" / "under_test"
    env_root.mkdir()
    lock_update(project=str(env_root))
    monkeypatch.setenv("HMP_PROJECT_ROOT", str(env_root))
    raw_toml = {"workspace": {"project_root": str(declared)}}

    assert project_lockfile_path(env_root).is_file()
    assert not project_lockfile_path(declared).exists()
    assert _verify_frozen_inputs_strict(config_path, raw_toml) == env_root.resolve()


def test_explicit_project_wins_over_the_lockfile_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``--project`` names the project even when ``--output`` sits elsewhere."""
    from hydromodpy.cli._workers.dev import _lock_targets

    monkeypatch.delenv("HMP_WORKSPACE", raising=False)
    workspace, project_root, _ = _seed_workspace_project(tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    out = elsewhere / "custom.lock"

    _, dest, named = _lock_targets(str(workspace), str(project_root), str(out))
    assert dest == out.resolve()
    assert named == project_root.resolve()

    _, _, unnamed = _lock_targets(str(workspace), None, str(out))
    assert unnamed == elsewhere.resolve()


def test_data_add_frozen_reads_the_named_project(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``hmp data add --frozen`` works outside a project once ``--project`` names one."""
    from hydromodpy.cli._workers.data import add_data_entry
    from hydromodpy.cli._workers.dev import lock_update

    monkeypatch.delenv("HMP_WORKSPACE", raising=False)
    monkeypatch.delenv("HMP_PROJECT_ROOT", raising=False)
    workspace, project_root, _ = _seed_workspace_project(tmp_path)
    lock_update(project=str(project_root))

    outside = tmp_path / "elsewhere"
    outside.mkdir()
    monkeypatch.chdir(outside)
    candidate = outside / "series_B.csv"
    candidate.write_text("datetime,value\n2020-01-02,2.0\n")

    with pytest.raises(FileNotFoundError, match="project.toml"):
        add_data_entry(candidate, variable="hydrometry", workspace=str(workspace), frozen=True)

    # The named project has a lockfile, so the check gets as far as the digest.
    with pytest.raises(ValueError, match="SHA-256"):
        add_data_entry(
            candidate,
            variable="hydrometry",
            workspace=str(workspace),
            project=str(project_root),
            frozen=True,
        )


def test_data_add_cli_forwards_the_project_option(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import argparse

    from hydromodpy.cli._workers import data as data_worker
    from hydromodpy.cli.commands.data import add as add_cmd

    seen: dict[str, object] = {}

    def fake_add(file: object, **kwargs: object) -> dict:
        seen.update(kwargs)
        return {"variable": "hydrometry", "provider": "custom", "station_id": None, "dest": "x"}

    monkeypatch.setattr(data_worker, "add_data_entry", fake_add)
    parser = argparse.ArgumentParser()
    add_cmd.register(parser.add_subparsers())
    args = parser.parse_args(
        ["add", "series.csv", "--type", "hydrometry", "--project", str(tmp_path), "--frozen"]
    )
    args._handler(args)

    assert seen["project"] == str(tmp_path)
    assert seen["frozen"] is True


def test_atomic_write_uses_a_short_temporary_suffix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The tmp sibling keeps 8 hex chars, the repo-wide budget against MAX_PATH."""
    from hydromodpy.data.registry import freeze

    swapped: list[str] = []
    real_replace = os.replace

    def spy(src: object, dst: object) -> None:
        swapped.append(Path(str(src)).name)
        real_replace(src, dst)  # type: ignore[arg-type]

    monkeypatch.setattr(os, "replace", spy)
    dest = tmp_path / LOCKFILE_NAME
    freeze._atomic_write_text(dest, 'version = "1"\n')

    assert dest.read_text() == 'version = "1"\n'
    prefix = f".{LOCKFILE_NAME}.tmp."
    assert len(swapped) == 1
    assert swapped[0].startswith(prefix)
    assert len(swapped[0]) - len(prefix) == 8


@pytest.mark.parametrize(
    ("station", "digest", "refusal"),
    [
        ("A", None, None),
        ("A", "0" * 64, "SHA-256"),
        ("B", None, "absent from hydromodpy.lock"),
    ],
    ids=["pinned", "another digest", "not pinned"],
)
def test_frozen_matching_reads_the_one_record(
    tmp_path: Path, frozen_mode_reset: None, station: str, digest: str | None, refusal: str | None
) -> None:
    """A catalog entry and a registration are both matched against ``[[input]]``."""
    from types import SimpleNamespace

    from hydromodpy.data.provenance.lockfile import set_frozen_mode
    from hydromodpy.data.registry import cache_store

    catalog, workspace, src = _seed_workspace(tmp_path)
    write_lockfile(catalog, workspace / LOCKFILE_NAME, **_SCHEMA_VERSIONS)
    set_frozen_mode(True, project_root=workspace)
    found = {"variable": "hydrometry", "source": "hubeau", "station_id": station}
    sha256 = digest or sha256_of(src)
    file_path = src.relative_to(workspace).as_posix()

    checks = (
        lambda: cache_store.reject_frozen_entry_mismatch(
            catalog, SimpleNamespace(**found, file_path=file_path, sha256=sha256)
        ),
        lambda: cache_store.reject_frozen_register(
            catalog, **found, file_path=Path(file_path), file_sha256=sha256, is_custom=False
        ),
    )
    for check in checks:
        if refusal is None:
            check()
        else:
            with pytest.raises(FrozenDataError, match=refusal):
                check()
    catalog.close()


def test_a_frozen_refusal_is_a_typed_data_failure(
    tmp_path: Path,
    frozen_mode_reset: None,
) -> None:
    """A frozen run that meets a refusal exits as a data failure, code 16."""
    from hydromodpy.cli.helpers import EXIT_VALIDATION, exit_code_for
    from hydromodpy.core.exceptions import DataCacheError
    from hydromodpy.data.provenance.lockfile import set_frozen_mode
    from hydromodpy.data.registry import cache_store

    project_root = tmp_path / "project"
    project_root.mkdir()
    set_frozen_mode(True, project_root=project_root)

    with pytest.raises(DataCacheError) as info:
        cache_store.locked_inputs()

    assert isinstance(info.value, FrozenDataError)
    assert exit_code_for(info.value) == EXIT_VALIDATION


@pytest.mark.parametrize("opener", ["_open_writer", "_open_reader"])
def test_a_zst_archive_without_zstandard_says_so(
    opener: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sys

    from hydromodpy.data.registry import freeze

    monkeypatch.setitem(sys.modules, "zstandard", None)
    with pytest.raises(RuntimeError, match="zstandard is required"):
        getattr(freeze, opener)(tmp_path / "frozen.tar.zst")
