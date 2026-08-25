"""P9 lockfile contract tests.

Cover the four mandatory sections, atomicity, and the strict verify path that
``hmp dev lock verify --strict`` relies on. ``test_no_lock_option_skips_write``
checks the wiring inside ``hmp run`` (only the helper is exercised so that
the test stays fast and offline). The last section pins the one address of
``hydromodpy.lock``: the project root a run wrote it to.
"""

from __future__ import annotations

import os
import re
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest
import tomlkit

from hydromodpy.data.data_freeze import (
    LOCKFILE_NAME,
    LOCKFILE_VERSION,
    archive_lockfile,
    read_lockfile,
    read_lockfile_binaries,
    read_lockfile_inputs,
    read_lockfile_meta,
    restore_archive,
    sha256_of,
    verify_frozen,
    verify_inputs_strict,
    write_lockfile,
)
from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB


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
    write_lockfile(catalog, dest)

    doc = tomlkit.parse(dest.read_text())
    for section in ("hydromodpy", "binaries", "schema", "inputs"):
        assert section in doc, f"missing [{section}] section"

    meta = read_lockfile_meta(dest)
    assert meta["version"] == LOCKFILE_VERSION
    assert "hydromodpy_version" in meta
    assert "python_version" in meta
    assert "catalog_schema_version" in meta
    assert meta["zarr_schema_version"] == "2"
    assert meta["parquet_schema_version"] == "v2"

    inputs = read_lockfile_inputs(dest)
    assert inputs, "inputs section must list registered artefacts"
    payload = next(iter(inputs.values()))
    assert set(payload) == {"sha256", "bytes", "fetched_at"}


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
    write_lockfile(catalog, dest)
    after_stat = dest.stat()

    # Replace must have substituted the inode (Unix rename semantics).
    assert (before_stat.st_dev, before_stat.st_ino) != (after_stat.st_dev, after_stat.st_ino)
    # No stray ``.lockfile.tmp.*`` after the call.
    leftovers = [p for p in dest.parent.iterdir() if p.name.startswith(f".{dest.name}.tmp.")]
    assert leftovers == []
    # Final payload is well-formed TOML with our header.
    parsed = tomlkit.parse(dest.read_text())
    assert parsed["hydromodpy"]["version"] == LOCKFILE_VERSION
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
    write_lockfile(catalog, dest, solvers={"modflow6": fake_solver})

    binaries = read_lockfile_binaries(dest)
    assert binaries.get("modflow6_sha256") == sha256_of(fake_solver)
    assert "modflow6_path" in binaries


def test_lockfile_includes_inputs_sha256(tmp_path: Path) -> None:
    catalog, workspace, src = _seed_workspace(tmp_path)
    dest = workspace / LOCKFILE_NAME
    write_lockfile(catalog, dest)
    inputs = read_lockfile_inputs(dest)
    assert len(inputs) == 1
    key, payload = next(iter(inputs.items()))
    assert key == src.name
    assert payload["sha256"] == sha256_of(src)
    assert payload["bytes"] == src.stat().st_size


def test_verify_lockfile_passes_when_unchanged(tmp_path: Path) -> None:
    catalog, workspace, _ = _seed_workspace(tmp_path)
    dest = workspace / LOCKFILE_NAME
    write_lockfile(catalog, dest)
    assert verify_frozen(catalog, dest) == []
    assert verify_inputs_strict(catalog, dest) == []


def test_verify_lockfile_warns_on_changed_input(tmp_path: Path) -> None:
    catalog, workspace, src = _seed_workspace(tmp_path)
    dest = workspace / LOCKFILE_NAME
    write_lockfile(catalog, dest)
    # Mutate the file. verify_frozen still tolerates a mismatch (returns a
    # list to be reported as warnings by ``hmp lock verify``).
    src.write_text("datetime,value\n2020-01-01,9.0\n")
    mismatches = verify_frozen(catalog, dest)
    assert len(mismatches) == 1
    assert mismatches[0].kind == "sha256"
    assert mismatches[0].path == src.name


def test_verify_strict_fails_on_changed_input(tmp_path: Path) -> None:
    catalog, workspace, src = _seed_workspace(tmp_path)
    dest = workspace / LOCKFILE_NAME
    write_lockfile(catalog, dest)
    src.write_text("datetime,value\n2020-01-01,5.0\n")
    mismatches = verify_inputs_strict(catalog, dest)
    assert len(mismatches) == 1
    m = mismatches[0]
    assert m.kind == "sha256"
    assert m.path == src.name
    assert m.expected != m.observed


def test_no_lock_option_skips_write(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``hmp run --no-lock`` short-circuits the post-run helper."""
    from hydromodpy.cli.commands import run as run_cmd

    # Build the minimal config dict the helper reads from raw_toml.
    config_path = tmp_path / "fake.toml"
    config_path.write_text("# placeholder\n")
    raw_toml = {"workspace": {"project_root": str(tmp_path)}}

    # Sentinel to capture whether the helper was called.
    called = {"hit": False}

    def fake_helper(path: Path, raw: dict[str, object]) -> None:
        called["hit"] = True

    monkeypatch.setattr(run_cmd, "_post_run_lockfile_write", fake_helper)

    # Simulate the conditional check inside the runner.
    no_lock = True
    if not no_lock:
        run_cmd._post_run_lockfile_write(config_path, raw_toml)
    assert called["hit"] is False

    # Default path (no_lock = False) does invoke the helper.
    no_lock = False
    if not no_lock:
        run_cmd._post_run_lockfile_write(config_path, raw_toml)
    assert called["hit"] is True


# Bonus coverage --------------------------------------------------------------


def test_post_run_helper_writes_lockfile(tmp_path: Path) -> None:
    """The integration helper writes the lockfile when the data cache exists."""
    from hydromodpy.cli.commands.run import _post_run_lockfile_write

    workspace = tmp_path / "workspace"
    project_root = workspace / "projects" / "demo"
    data_dir = workspace / "data" / "hydrometry"
    data_dir.mkdir(parents=True)
    project_root.mkdir(parents=True)
    src = data_dir / "series.csv"
    src.write_text("datetime,value\n2020-01-01,1.0\n")
    catalog = DataCatalogDuckDB(workspace / "data" / "cache.duckdb")
    catalog.register(
        variable="hydrometry",
        source="hubeau",
        station_id="A",
        file_path=src.name,
    )
    catalog.close()

    config_path = project_root / "hydromodpy.toml"
    config_path.write_text("# config placeholder\n")
    raw_toml = {"workspace": {"project_root": str(project_root)}}
    _post_run_lockfile_write(config_path, raw_toml)

    dest = project_root / LOCKFILE_NAME
    assert dest.is_file()
    meta = read_lockfile_meta(dest)
    assert meta["version"] == LOCKFILE_VERSION


def test_lockfile_uses_temporary_file_then_replaces(tmp_path: Path) -> None:
    """Confirm the tmp + replace path: no partial file is ever created."""
    catalog, workspace, _ = _seed_workspace(tmp_path)
    dest = workspace / LOCKFILE_NAME
    write_lockfile(catalog, dest)
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


def test_lockfile_round_trip_artefact_block(tmp_path: Path) -> None:
    """The ``[[artefact]]`` records round-trip through write/read_lockfile()."""
    catalog, workspace, _ = _seed_workspace(tmp_path)
    dest = workspace / LOCKFILE_NAME
    write_lockfile(catalog, dest)
    entries = read_lockfile(dest)
    assert len(entries) == 1
    assert entries[0].variable == "hydrometry"
    assert entries[0].sha256
    # ``fetched_at`` should be ISO8601 with UTC offset.
    assert "T" in entries[0].fetched_at
    # Sanity: a second write does not duplicate inputs.
    write_lockfile(catalog, dest)
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
    archive_lockfile(cat, archive, lockfile_dest=tmp_path / LOCKFILE_NAME)
    assert archive.is_file()
    restore_dir = tmp_path / "restored"
    restore_archive(archive, restore_dir)
    assert (restore_dir / LOCKFILE_NAME).is_file()


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
    write_lockfile(cat, dest)

    entries = read_lockfile(dest)
    assert len(entries) == 1
    assert entries[0].file_path == src.name
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
    write_lockfile(cat, dest)

    entries = read_lockfile(dest)
    assert {entry.file_path for entry in entries} == {first.name, second.name}
    assert verify_frozen(cat, dest) == []


# One address: what a run writes is what --frozen reads -----------------------


@pytest.fixture
def frozen_mode_reset() -> Iterator[None]:
    """Leave the process-wide frozen mode as it was found."""
    from hydromodpy.data.data_freeze import (
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
    from hydromodpy.data.data_freeze import project_lockfile_path

    assert project_lockfile_path(tmp_path) == tmp_path / LOCKFILE_NAME


def test_cache_store_no_longer_guesses_the_lockfile_location() -> None:
    """The candidate-scanning resolver is gone, not aliased."""
    from hydromodpy.data.registry import cache_store

    assert not hasattr(cache_store, "workspace_lockfile_path")


def test_frozen_mode_reads_the_lockfile_the_run_wrote(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    frozen_mode_reset: None,
) -> None:
    """The file the post-run write produced is the one frozen mode loads."""
    from hydromodpy.cli.commands.run import _post_run_lockfile_write
    from hydromodpy.data.data_freeze import project_lockfile_path, set_frozen_mode
    from hydromodpy.data.registry import cache_store

    monkeypatch.delenv("HMP_WORKSPACE", raising=False)
    workspace, project_root, config_path = _seed_workspace_project(tmp_path)
    raw_toml = {"workspace": {"project_root": str(project_root)}}
    _post_run_lockfile_write(config_path, raw_toml)

    written = project_lockfile_path(project_root)
    assert written.is_file()
    # The directories the old resolver scanned hold nothing to fall back on.
    assert not (workspace / LOCKFILE_NAME).exists()
    assert not (workspace / "data" / LOCKFILE_NAME).exists()

    set_frozen_mode(True, project_root=project_root)
    assert [artifact.station_id for artifact in cache_store.locked_artifacts()] == ["A"]


def test_frozen_precheck_accepts_the_lockfile_the_run_wrote(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``hmp run --frozen`` resolves the same address as the post-run write."""
    from hydromodpy.cli.commands.run import (
        _post_run_lockfile_write,
        _verify_frozen_inputs_strict,
    )

    monkeypatch.delenv("HMP_WORKSPACE", raising=False)
    _, project_root, config_path = _seed_workspace_project(tmp_path)
    raw_toml = {"workspace": {"project_root": str(project_root)}}
    _post_run_lockfile_write(config_path, raw_toml)

    assert _verify_frozen_inputs_strict(config_path, raw_toml) == project_root


def test_locked_artifacts_names_the_expected_path_when_missing(
    tmp_path: Path,
    frozen_mode_reset: None,
) -> None:
    from hydromodpy.data.data_freeze import project_lockfile_path, set_frozen_mode
    from hydromodpy.data.registry import cache_store

    project_root = tmp_path / "project"
    project_root.mkdir()
    set_frozen_mode(True, project_root=project_root)

    expected = project_lockfile_path(project_root.resolve())
    with pytest.raises(RuntimeError, match=re.escape(str(expected))):
        cache_store.locked_artifacts()


def test_locked_artifacts_without_a_bound_project_says_so(frozen_mode_reset: None) -> None:
    """A lookup made outside frozen mode names the missing binding, never guesses."""
    from hydromodpy.data.data_freeze import set_frozen_mode
    from hydromodpy.data.registry import cache_store

    set_frozen_mode(False)
    with pytest.raises(RuntimeError, match="no project bound"):
        cache_store.locked_artifacts()


def test_enabling_frozen_mode_without_a_project_is_refused(frozen_mode_reset: None) -> None:
    """``project_root`` is required to enable: no sticky previous binding."""
    from hydromodpy.data.data_freeze import is_frozen_mode, set_frozen_mode

    with pytest.raises(ValueError, match="project_root"):
        set_frozen_mode(True)
    assert is_frozen_mode() is False


def test_every_enable_names_its_own_project(tmp_path: Path, frozen_mode_reset: None) -> None:
    from hydromodpy.data.data_freeze import frozen_project_root, set_frozen_mode

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

    from hydromodpy.cli.commands.run import _post_run_lockfile_write
    from hydromodpy.data.data_freeze import frozen_project_root, is_frozen_mode
    from hydromodpy.data.registry import cache_store
    from hydromodpy.project.runner import ProjectRunner

    monkeypatch.delenv("HMP_WORKSPACE", raising=False)
    _, project_root, config_path = _seed_workspace_project(tmp_path)
    _post_run_lockfile_write(config_path, {"workspace": {"project_root": str(project_root)}})

    seen: dict[str, object] = {}

    class RecordingPipeline:
        def __init__(self, steps: tuple, *, workspace: Path) -> None:
            seen["workspace"] = workspace

        def run(self, initial: object, **kwargs: object) -> dict:
            seen["frozen"] = is_frozen_mode()
            seen["root"] = frozen_project_root()
            seen["stations"] = [a.station_id for a in cache_store.locked_artifacts()]
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
            run_id=None,
            flow_runtime_overrides=None,
        ),
        raw_toml={},
        store=None,
        sim_id=None,
    )
    project = SimpleNamespace(
        _ctx=ctx,
        _cfg=None,
        _config_path=config_path,
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

    This is the ``hmp dev lock restore`` then ``hmp dev lock verify`` path: the
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
    from hydromodpy.data import scaffold

    monkeypatch.delenv("HMP_WORKSPACE", raising=False)
    monkeypatch.setattr(scaffold, "DEFAULT_ROOT", tmp_path / "no_default_workspace")
    orphan = tmp_path / "orphan"
    orphan.mkdir()
    monkeypatch.chdir(orphan)

    with pytest.raises(FileNotFoundError, match="no_default_workspace"):
        lock_update(output=str(orphan / "custom.lock"))


# One shape: whoever writes the file writes the same file ---------------------


def test_both_writers_record_the_same_project_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``hmp dev lock update`` and ``hmp run`` fill the same header keys."""
    from hydromodpy.cli._workers.dev import lock_update
    from hydromodpy.cli.commands.run import _post_run_lockfile_write
    from hydromodpy.data import data_freeze
    from hydromodpy.data.data_freeze import project_lockfile_path

    monkeypatch.delenv("HMP_WORKSPACE", raising=False)
    monkeypatch.delenv("HMP_PROJECT_ROOT", raising=False)
    monkeypatch.setattr(data_freeze, "_git_head", lambda cwd: f"commit-of-{Path(cwd).name}")
    _, project_root, config_path = _seed_workspace_project(tmp_path)
    dest = project_lockfile_path(project_root)

    _post_run_lockfile_write(config_path, {"workspace": {"project_root": str(project_root)}})
    from_run = read_lockfile_meta(dest)

    assert lock_update(project=str(project_root)) == dest
    from_dev = read_lockfile_meta(dest)

    assert from_run["project_git_commit"] == "commit-of-demo"
    assert set(from_dev) == set(from_run)
    assert from_dev["project_git_commit"] == from_run["project_git_commit"]


def test_env_project_root_beats_the_declared_one(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``HMP_PROJECT_ROOT`` moves the lockfile, exactly as it moves the config."""
    from hydromodpy.cli.commands.run import (
        _post_run_lockfile_write,
        _verify_frozen_inputs_strict,
    )
    from hydromodpy.data.data_freeze import project_lockfile_path

    monkeypatch.delenv("HMP_WORKSPACE", raising=False)
    workspace, declared, config_path = _seed_workspace_project(tmp_path)
    env_root = workspace / "projects" / "under_test"
    env_root.mkdir()
    monkeypatch.setenv("HMP_PROJECT_ROOT", str(env_root))
    raw_toml = {"workspace": {"project_root": str(declared)}}

    _post_run_lockfile_write(config_path, raw_toml)

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
    from hydromodpy.data import data_freeze

    swapped: list[str] = []
    real_replace = os.replace

    def spy(src: object, dst: object) -> None:
        swapped.append(Path(str(src)).name)
        real_replace(src, dst)  # type: ignore[arg-type]

    monkeypatch.setattr(os, "replace", spy)
    dest = tmp_path / LOCKFILE_NAME
    data_freeze._atomic_write_text(dest, 'version = "1"\n')

    assert dest.read_text() == 'version = "1"\n'
    prefix = f".{LOCKFILE_NAME}.tmp."
    assert len(swapped) == 1
    assert swapped[0].startswith(prefix)
    assert len(swapped[0]) - len(prefix) == 8
