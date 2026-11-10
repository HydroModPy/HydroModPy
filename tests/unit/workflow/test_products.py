"""``ask``: the one path from a step to the product store, on a fake kind."""

from __future__ import annotations

import json
import logging
import pickle
from pathlib import Path
from types import SimpleNamespace

import pytest

from hydromodpy.core.state.run_state import WorkflowContext
from hydromodpy.results.products.cited import CitedProduct, read_cited, write_cited
from hydromodpy.results.products.store import ProductStore, products_root
from hydromodpy.workflow import products as products_module
from hydromodpy.workflow.products import ProductKind, ask, write_products

FAKE_KIND = ProductKind(
    package="mesh",
    step="build_mesh",
    write=lambda value, directory: (directory / "value.txt").write_text(value, encoding="utf-8"),
)


@pytest.fixture(autouse=True)
def _fake_kind(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(products_module.PRODUCT_KINDS, "fake", FAKE_KIND)


def _ctx(
    tmp_path: Path,
    *,
    resumed: bool = False,
    lightweight: bool = False,
    run_dir: Path | None = None,
) -> WorkflowContext:
    cfg = SimpleNamespace(workspace=SimpleNamespace(products_cap_mb=5000, project_root=tmp_path))
    ctx = WorkflowContext(cfg=cfg, config_path=tmp_path / "project.toml", raw_toml={})
    ctx.setup.workspace = tmp_path
    ctx.execution.resumed = resumed
    ctx.execution.lightweight = lightweight
    ctx.run_dir = run_dir if run_dir is not None else tmp_path / "runs" / "a"
    ctx.run_dir.mkdir(parents=True, exist_ok=True)
    return ctx


def _seed(root: Path, key: str, *, bytes_: int, written_at: float) -> None:
    path = root / key[:2] / key
    path.mkdir(parents=True)
    (path / "data.bin").write_bytes(b"x" * bytes_)
    (path / "meta.json").write_text(
        json.dumps({"key": key, "kind": "fake", "bytes": bytes_, "written_at": written_at}),
        encoding="utf-8",
    )


def _read_value(directory: Path) -> str:
    return (directory / "value.txt").read_text(encoding="utf-8")


def test_a_miss_builds_deposits_and_cites(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    key = "a" * 64
    built: list[int] = []

    value = ask(
        ctx,
        "fake",
        key=key,
        build=lambda: built.append(1) or "made",
        read=_read_value,
    )

    assert value == "made"
    assert built == [1]
    store = ProductStore(products_root(tmp_path))
    assert store.get(key) is not None
    assert ctx.setup.products["fake"] == key
    assert read_cited(ctx.run_dir) == ()
    write_products(ctx)
    assert read_cited(ctx.run_dir) == (CitedProduct("fake", key),)


def test_ask_never_writes_products_json_of_a_run(tmp_path: Path) -> None:
    """A verb called after a run reaches ask with the run directory still bound."""
    ctx = _ctx(tmp_path)
    write_cited(ctx.run_dir, [CitedProduct("fake", "b" * 64)])

    ask(ctx, "fake", key="a" * 64, build=lambda: "made", read=_read_value)

    assert read_cited(ctx.run_dir) == (CitedProduct("fake", "b" * 64),)


def test_a_sealed_run_keeps_its_products_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = _ctx(tmp_path)
    write_cited(ctx.run_dir, [CitedProduct("fake", "b" * 64)])
    ctx.setup.products = {"fake": "a" * 64}
    monkeypatch.setattr(products_module, "is_sealed", lambda run_dir: True)

    write_products(ctx)

    assert read_cited(ctx.run_dir) == (CitedProduct("fake", "b" * 64),)


def test_a_context_that_asked_pickles(tmp_path: Path) -> None:
    """A parallel calibration sends the setup to its workers by pickle."""
    ctx = _ctx(tmp_path)
    ask(ctx, "fake", key="a" * 64, build=lambda: "made", read=_read_value)

    assert pickle.loads(pickle.dumps(ctx.setup)).products == {"fake": "a" * 64}


def test_a_present_product_is_read_without_build(tmp_path: Path) -> None:
    key = "a" * 64
    store = ProductStore(products_root(tmp_path))
    store.put(key, "fake", lambda d: (d / "value.txt").write_text("made", encoding="utf-8"))
    ctx = _ctx(tmp_path)
    built: list[int] = []

    value = ask(ctx, "fake", key=key, build=lambda: built.append(1) or "x", read=_read_value)

    assert value == "made"
    assert built == []


def test_an_unreadable_product_is_discarded_and_rebuilt(tmp_path: Path) -> None:
    key = "a" * 64
    store = ProductStore(products_root(tmp_path))
    store.put(key, "fake", lambda d: (d / "value.txt").write_text("corrupt", encoding="utf-8"))
    ctx = _ctx(tmp_path)

    def read(directory: Path) -> str:
        raise ValueError("cannot decode")

    value = ask(ctx, "fake", key=key, build=lambda: "rebuilt", read=read)

    assert value == "rebuilt"
    assert (store.get(key) / "value.txt").read_text(encoding="utf-8") == "rebuilt"


def test_a_lightweight_trial_reads_and_never_writes(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, lightweight=True)
    key = "a" * 64
    built: list[int] = []

    value = ask(ctx, "fake", key=key, build=lambda: built.append(1) or "made", read=_read_value)

    assert value == "made"
    assert built == [1]
    assert ProductStore(products_root(tmp_path)).get(key) is None
    assert ctx.setup.products["fake"] == key


def test_a_resume_asks_for_the_cited_key(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "a"
    run_dir.mkdir(parents=True)
    cited_key = "b" * 64
    write_cited(run_dir, [CitedProduct("fake", cited_key)])
    store = ProductStore(products_root(tmp_path))
    store.put(cited_key, "fake", lambda d: (d / "value.txt").write_text("cited", encoding="utf-8"))
    ctx = _ctx(tmp_path, resumed=True, run_dir=run_dir)

    value = ask(ctx, "fake", key="a" * 64, build=lambda: "rebuilt", read=_read_value)

    assert value == "cited"
    assert ctx.setup.products["fake"] == cited_key


def test_a_resume_whose_cited_product_is_gone_builds_under_the_recomputed_key(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "runs" / "a"
    run_dir.mkdir(parents=True)
    cited_key, key = "b" * 64, "a" * 64
    write_cited(run_dir, [CitedProduct("fake", cited_key)])
    ctx = _ctx(tmp_path, resumed=True, run_dir=run_dir)

    value = ask(ctx, "fake", key=key, build=lambda: "rebuilt", read=_read_value)

    store = ProductStore(products_root(tmp_path))
    assert value == "rebuilt"
    assert store.get(cited_key) is None
    assert store.get(key) is not None
    assert ctx.setup.products["fake"] == key


@pytest.mark.parametrize("rebuild_differs", [True, False])
def test_a_rebuild_during_resume_warns_only_when_it_may_differ(
    tmp_path: Path, caplog, rebuild_differs: bool
) -> None:
    ctx = _ctx(tmp_path, resumed=True)
    key = "a" * 64

    with caplog.at_level(logging.WARNING):
        value = ask(
            ctx,
            "fake",
            key=key,
            build=lambda: "rebuilt",
            read=_read_value,
            rebuild_differs=rebuild_differs,
        )

    assert value == "rebuilt"
    assert ("differs" in caplog.text) is rebuild_differs


def test_setup_products_is_replaced_not_mutated(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    before = ctx.setup.products
    key = "a" * 64

    ask(ctx, "fake", key=key, build=lambda: "made", read=_read_value)

    assert ctx.setup.products is not before
    assert ctx.setup.products["fake"] == key
    assert "fake" not in before


def test_the_writer_evicts_but_keeps_its_own_key(tmp_path: Path) -> None:
    store = ProductStore(products_root(tmp_path))
    old = "b" * 64
    _seed(store.root, old, bytes_=10_000_000, written_at=1.0)
    ctx = _ctx(tmp_path)
    ctx.cfg.workspace.products_cap_mb = 1
    key = "a" * 64

    ask(ctx, "fake", key=key, build=lambda: "made", read=_read_value)

    assert store.get(key) is not None
    assert store.get(old) is None


def test_a_put_that_fails_on_disk_does_not_fail_the_step(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = _ctx(tmp_path)
    key = "a" * 64

    def failing_put(self, key: str, kind: str, write) -> Path:
        raise OSError("disk full")

    monkeypatch.setattr(ProductStore, "put", failing_put)

    value = ask(ctx, "fake", key=key, build=lambda: "made", read=_read_value)

    assert value == "made"
    assert ctx.setup.products["fake"] == key


def test_an_unreadable_products_json_of_a_running_run_skips_the_eviction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = ProductStore(products_root(tmp_path))
    old = "b" * 64
    _seed(store.root, old, bytes_=10_000_000, written_at=1.0)
    ctx = _ctx(tmp_path)
    ctx.cfg.workspace.products_cap_mb = 1

    def unreadable(project_root: Path) -> frozenset[str]:
        raise ValueError("products.json schema is 'future'")

    monkeypatch.setattr(products_module, "alive_keys", unreadable)

    value = ask(ctx, "fake", key="a" * 64, build=lambda: "made", read=_read_value)

    assert value == "made"
    assert store.get(old) is not None
