"""The product store: build once, read, evict, sweep, and the refusals."""

from __future__ import annotations

import json
import multiprocessing
import os
import socket
import time
from pathlib import Path

import pytest

from hydromodpy.core.state.layout import PRODUCTS_DIRNAME, internal_dir
from hydromodpy.results.products.store import META_FILENAME, ProductStore, products_root


def _key(char: str) -> str:
    """A valid sha256-shaped key made of one repeated hexadecimal character."""
    return char * 64


def _seed(root: Path, key: str, *, bytes_: int, written_at: float, kind: str = "mesh") -> Path:
    """Write one product directly, with a controlled size and date."""
    path = ProductStore(root).path(key)
    path.mkdir(parents=True)
    (path / "data.bin").write_bytes(b"x" * bytes_)
    meta = {"key": key, "kind": kind, "bytes": bytes_, "written_at": written_at}
    (path / META_FILENAME).write_text(json.dumps(meta), encoding="utf-8")
    return path


def test_products_root_lives_under_the_internal_dir(tmp_path: Path) -> None:
    project = tmp_path / "project"
    assert products_root(project) == internal_dir(project) / PRODUCTS_DIRNAME


def test_a_missing_product_reads_none(tmp_path: Path) -> None:
    assert ProductStore(tmp_path / "products").get(_key("a")) is None


def test_a_product_is_built_once_then_read(tmp_path: Path) -> None:
    store = ProductStore(tmp_path / "products")
    key = _key("a")
    calls: list[int] = []

    def write(directory: Path) -> None:
        calls.append(1)
        (directory / "value.txt").write_text("made", encoding="utf-8")

    path = store.put(key, "mesh", write)
    assert path == store.path(key)
    assert (path / META_FILENAME).is_file()
    assert (path / "value.txt").read_text(encoding="utf-8") == "made"
    assert calls == [1]

    again = store.put(key, "mesh", write)
    assert again == path
    assert calls == [1]


def test_a_failing_write_is_not_called_when_the_product_exists(tmp_path: Path) -> None:
    store = ProductStore(tmp_path / "products")
    key = _key("a")
    store.put(key, "mesh", lambda directory: (directory / "value.txt").write_text("made"))

    def boom(directory: Path) -> None:
        raise AssertionError("write must not run when the product exists")

    assert store.put(key, "mesh", boom) == store.path(key)


def _spawn_put(root: str, key: str) -> int:
    ProductStore(Path(root)).put(key, "mesh", lambda d: (d / "value.txt").write_text("made"))
    return 0


def test_two_spawned_writers_build_one_product(tmp_path: Path) -> None:
    root = tmp_path / "products"
    key = _key("a")
    context = multiprocessing.get_context("spawn")
    with context.Pool(2) as pool:
        codes = pool.starmap(_spawn_put, [(str(root), key), (str(root), key)])
    assert codes == [0, 0]
    store = ProductStore(root)
    assert len(store.entries()) == 1
    assert (store.path(key) / "value.txt").read_text(encoding="utf-8") == "made"
    assert json.loads((store.path(key) / META_FILENAME).read_text(encoding="utf-8"))["key"] == key


def test_a_rename_lost_to_a_neighbour_returns_the_neighbours_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = ProductStore(tmp_path / "products")
    key = _key("a")
    target = store.path(key)
    target.mkdir(parents=True)
    (target / "value.txt").write_text("theirs", encoding="utf-8")
    (target / META_FILENAME).write_text(
        json.dumps({"key": key, "kind": "mesh", "bytes": 6, "written_at": 0.0}),
        encoding="utf-8",
    )

    def fail_rename(source: object, destination: object) -> None:
        raise OSError("a neighbour finished first")

    monkeypatch.setattr(os, "rename", fail_rename)
    assert store.put(key, "mesh", lambda d: (d / "value.txt").write_text("mine")) == target
    assert (target / "value.txt").read_text(encoding="utf-8") == "theirs"


def test_eviction_removes_the_oldest_first(tmp_path: Path) -> None:
    store = ProductStore(tmp_path / "products")
    old, new = _key("a"), _key("b")
    _seed(store.root, old, bytes_=100, written_at=1.0)
    _seed(store.root, new, bytes_=100, written_at=2.0)

    report = store.evict(100)

    assert report.removed == (old,)
    assert report.freed == 100
    assert report.total_after == 100
    assert store.get(old) is None
    assert store.get(new) is not None


def test_eviction_ties_by_key(tmp_path: Path) -> None:
    store = ProductStore(tmp_path / "products")
    first, second = _key("a"), _key("b")
    _seed(store.root, first, bytes_=100, written_at=1.0)
    _seed(store.root, second, bytes_=100, written_at=1.0)

    report = store.evict(100)

    assert report.removed == (first,)
    assert store.get(first) is None
    assert store.get(second) is not None


def test_a_kept_key_is_never_removed(tmp_path: Path) -> None:
    store = ProductStore(tmp_path / "products")
    kept, gone = _key("a"), _key("b")
    _seed(store.root, kept, bytes_=100, written_at=1.0)
    _seed(store.root, gone, bytes_=100, written_at=2.0)

    report = store.evict(100, keep={kept})

    assert report.removed == (gone,)
    assert report.protected == (kept,)
    assert store.get(kept) is not None
    assert store.get(gone) is None


def test_over_cap_is_true_when_protected_alone_exceed_the_cap(tmp_path: Path) -> None:
    store = ProductStore(tmp_path / "products")
    first, second = _key("a"), _key("b")
    _seed(store.root, first, bytes_=150, written_at=1.0)
    _seed(store.root, second, bytes_=150, written_at=2.0)

    report = store.evict(100, keep={first, second})

    assert report.removed == ()
    assert report.protected == (first, second)
    assert report.over_cap is True
    assert report.total_after == 300
    assert store.get(first) is not None
    assert store.get(second) is not None


def test_a_dry_run_removes_nothing_and_reports_the_same(tmp_path: Path) -> None:
    store = ProductStore(tmp_path / "products")
    first, second = _key("a"), _key("b")
    _seed(store.root, first, bytes_=100, written_at=1.0)
    _seed(store.root, second, bytes_=100, written_at=2.0)
    dead = _writer_dir(store.root, _key("c"), pid=2**30, age_s=10)

    report = store.evict(100, dry_run=True)

    assert report.removed == (first,)
    assert report.freed == 100
    assert report.total_after == 100
    assert store.get(first) is not None
    assert store.get(second) is not None
    assert dead.exists()


def test_discard_removes_a_product(tmp_path: Path) -> None:
    store = ProductStore(tmp_path / "products")
    key = _key("a")
    store.put(key, "mesh", lambda directory: (directory / "value.txt").write_text("made"))
    store.discard(key)
    assert store.get(key) is None


def _writer_dir(root: Path, key: str, *, pid: int, age_s: float) -> Path:
    path = root / ".tmp" / f"{key}.{socket.gethostname()}.{pid}.deadbeef"
    path.mkdir(parents=True)
    (path / "file.txt").write_text("x", encoding="utf-8")
    stamp = time.time() - age_s
    os.utime(path, (stamp, stamp))
    return path


def test_a_tmp_of_a_dead_writer_is_swept_and_a_living_one_kept(tmp_path: Path) -> None:
    store = ProductStore(tmp_path / "products")
    store.root.mkdir(parents=True)
    dead = _writer_dir(store.root, _key("a"), pid=2**30, age_s=10)
    alive = _writer_dir(store.root, _key("b"), pid=os.getpid(), age_s=3600)

    store._sweep()

    assert not dead.exists()
    assert alive.exists()


def test_an_unreadable_meta_counts_as_absent(tmp_path: Path) -> None:
    store = ProductStore(tmp_path / "products")
    key = _key("a")
    store.path(key).mkdir(parents=True)
    (store.path(key) / META_FILENAME).write_text("not json", encoding="utf-8")

    assert store.entries() == []
    assert store.get(key) is not None  # the folder carries meta.json; the read decides


@pytest.mark.parametrize("key", ["", "abc", "z" * 64, "A" * 64, "g" * 64, "0" * 63 + "x"])
def test_a_key_that_is_not_a_sha256_is_refused(tmp_path: Path, key: str) -> None:
    store = ProductStore(tmp_path / "products")
    with pytest.raises(ValueError, match="not a product key"):
        store.get(key)
    with pytest.raises(ValueError, match="not a product key"):
        store.discard(key)
