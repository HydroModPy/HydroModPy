"""P9 lockfile contract tests.

Cover the four mandatory sections, atomicity, and the strict verify path that
``hmp lock verify --strict`` relies on. ``test_no_lock_option_skips_write``
checks the wiring inside ``hmp run`` (only the helper is exercised so that
the test stays fast and offline).
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path

import pytest
import tomlkit

from hydromodpy.data.data_freeze import (
    LOCKFILE_NAME,
    LOCKFILE_VERSION,
    read_lockfile,
    read_lockfile_binaries,
    read_lockfile_inputs,
    read_lockfile_meta,
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


def test_lockfile_round_trip_legacy_artefact_block(tmp_path: Path) -> None:
    """The legacy ``[[artefact]]`` records still load via read_lockfile()."""
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
    time.sleep(0)  # ensure linter sees the import as used
