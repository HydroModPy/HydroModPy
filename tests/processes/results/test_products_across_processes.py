"""Two processes that build one product leave one product, read whole."""

from __future__ import annotations

import json
import multiprocessing
from pathlib import Path

from hydromodpy.results.products.store import META_FILENAME, ProductStore


def _key(char: str) -> str:
    """A valid sha256-shaped key made of one repeated hexadecimal character."""
    return char * 64


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
