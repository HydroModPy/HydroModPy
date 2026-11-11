"""The index file: its lock, its staging copy in blocks of 16 KiB, its publication and its readers."""

from __future__ import annotations

import json
import os
import socket
import time
from pathlib import Path

import duckdb
import pytest

from hydromodpy.core.exceptions import CatalogUnreadableError, WriteConflictError
from hydromodpy.core.io.lock_file import LockFile
from hydromodpy.core.state.layout import catalog_path_for
from hydromodpy.results.catalog.index_file import (
    INDEX_ALIAS,
    INDEX_LEASE_S,
    INDEX_LOCK_NAME,
    discard_staging,
    index_lock,
    index_lock_path,
    new_staging,
    open_index,
    open_staging,
    publish_staging,
)
from tests._helpers.sealed_runs import make_project


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return make_project(tmp_path / "demo")


def _publish_value(root: Path, value: int) -> None:
    """Publish an index holding one table ``t`` with one row ``value``."""
    index_path = catalog_path_for(root)
    with index_lock(root) as lock:
        staging = new_staging(index_path, copy_of=None)
        connection = open_staging(staging)
        connection.execute("CREATE TABLE t (x INTEGER)")
        connection.execute("INSERT INTO t VALUES (?)", [value])
        connection.execute("CHECKPOINT")
        connection.close()
        publish_staging(staging, index_path, lock)


def _value(connection: duckdb.DuckDBPyConnection) -> int:
    return int(connection.execute("SELECT x FROM t").fetchone()[0])


def _foreign_lock(root: Path) -> dict:
    """Write a fresh lock in the name of a live process of this host that is not this one."""
    holder = {"pid": os.getppid(), "host": socket.gethostname(), "created": time.time()}
    path = index_lock_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(holder), encoding="utf-8")
    return holder


# -- the lock ---------------------------------------------------------------


def test_the_lock_lies_beside_the_index(root):
    assert index_lock_path(root) == catalog_path_for(root).with_name(INDEX_LOCK_NAME)
    assert index_lock_path(root).name == "index.duckdb.lock"


def test_the_lock_names_its_holder_and_goes_on_exit(root):
    with index_lock(root) as lock:
        holder = json.loads(index_lock_path(root).read_text(encoding="utf-8"))
        assert holder["pid"] == os.getpid()
        assert holder["host"] == socket.gethostname()
        assert abs(holder["created"] - time.time()) < 60
        assert lock.stale_after_s == INDEX_LEASE_S
    assert not index_lock_path(root).exists()


def test_the_lock_goes_on_an_exception_too(root):
    with pytest.raises(RuntimeError, match="inside"), index_lock(root):
        raise RuntimeError("inside")
    assert not index_lock_path(root).exists()


def test_a_wait_that_expires_names_the_holder(root):
    holder = _foreign_lock(root)

    with pytest.raises(WriteConflictError) as refused, index_lock(root, wait_s=0.05):
        pass

    message = str(refused.value)
    assert f"process {holder['pid']} on {holder['host']} since " in message
    assert "remove .hmp/index.duckdb.lock once that process is gone" in message
    assert "the runs on disk are untouched" in message
    assert index_lock_path(root).exists(), "a lock of another process is left to it"


# -- the staging file ---------------------------------------------------------


@pytest.mark.parametrize(
    ("copied", "block_size"),
    [(False, 16384), (True, 16384)],
    ids=["new", "copy-of-a-new-index"],
)
def test_a_staging_file_has_blocks_of_16_kib(root, copied, block_size):
    index_path = catalog_path_for(root)
    if copied:
        _publish_value(root, 1)
    staging = new_staging(index_path, copy_of=index_path if copied else None)
    try:
        connection = open_staging(staging)
        try:
            size = connection.execute("SELECT block_size FROM pragma_database_size()").fetchone()
        finally:
            connection.close()
        assert int(size[0]) == block_size
        assert staging.name.startswith("index.duckdb.rebuild-")
    finally:
        discard_staging(staging)
    assert not staging.exists()


def test_a_staging_copy_starts_from_the_published_index(root):
    _publish_value(root, 7)
    index_path = catalog_path_for(root)

    staging = new_staging(index_path, copy_of=index_path)
    connection = open_staging(staging)
    try:
        assert _value(connection) == 7
    finally:
        connection.close()
        discard_staging(staging)


def test_discarding_a_missing_staging_file_is_no_error(root):
    discard_staging(catalog_path_for(root).with_name("index.duckdb.rebuild-00000000"))


# -- publication --------------------------------------------------------------


def test_a_publication_replaces_the_index_and_leaves_no_staging(root):
    _publish_value(root, 1)
    _publish_value(root, 2)

    connection = open_index(root)
    try:
        assert _value(connection) == 2
    finally:
        connection.close()
    hmp_dir = catalog_path_for(root).parent
    assert list(hmp_dir.glob("*.rebuild-*")) == []
    assert not catalog_path_for(root).with_name("index.duckdb.wal").exists()


@pytest.mark.parametrize(
    "lose",
    ["released", "taken_back", "never_taken"],
)
def test_a_staging_file_is_not_published_without_the_lock(root, lose):
    _publish_value(root, 1)
    index_path = catalog_path_for(root)
    before = index_path.read_bytes()
    lock = LockFile(index_lock_path(root), stale_after_s=INDEX_LEASE_S, wait_s=0.0)
    if lose != "never_taken":
        assert lock.acquire()
    if lose == "released":
        lock.release()
    if lose == "taken_back":
        _foreign_lock(root)
    staging = new_staging(index_path, copy_of=index_path)
    try:
        with pytest.raises(WriteConflictError) as refused:
            publish_staging(staging, index_path, lock)
    finally:
        discard_staging(staging)

    assert "another process took .hmp/index.duckdb.lock while this one wrote" in str(refused.value)
    assert "the index it wrote is dropped" in str(refused.value)
    assert index_path.read_bytes() == before


# -- readers ------------------------------------------------------------------


def test_open_index_reads_only(root):
    _publish_value(root, 1)

    connection = open_index(root)
    try:
        with pytest.raises(duckdb.Error):
            connection.execute("INSERT INTO t VALUES (2)")
        assert connection.execute("SELECT current_database()").fetchone()[0] == INDEX_ALIAS
    finally:
        connection.close()


def test_open_index_without_an_index_is_file_not_found(root):
    with pytest.raises(FileNotFoundError, match="the project has no index yet"):
        open_index(root)


def test_open_index_on_a_broken_file_is_unreadable(root):
    index_path = catalog_path_for(root)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_bytes(b"not a database")

    with pytest.raises(CatalogUnreadableError, match="hmp catalog reindex"):
        open_index(root)


def test_an_open_reader_keeps_its_snapshot_across_a_publication(root):
    _publish_value(root, 1)
    reader = open_index(root)
    try:
        _publish_value(root, 2)

        assert _value(reader) == 1
        fresh = open_index(root)
        try:
            assert _value(fresh) == 2
        finally:
            fresh.close()
    finally:
        reader.close()
