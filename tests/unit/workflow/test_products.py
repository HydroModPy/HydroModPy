"""``ask``: the one path from a step to the product store, on a fake kind."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

from hydromodpy.catchment.algorithms.flow_products import TerrainRequest
from hydromodpy.core.state.run_state import WorkflowContext
from hydromodpy.results.products.cited import CitedProduct, read_cited, write_cited
from hydromodpy.results.products.store import ProductStore, products_root
from hydromodpy.workflow import products as products_module
from hydromodpy.workflow.products import ProductKind, ask, terrain_supply, write_products

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


def test_a_sealed_run_keeps_its_products_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = _ctx(tmp_path)
    write_cited(ctx.run_dir, [CitedProduct("fake", "b" * 64)])
    ctx.setup.products = {"fake": "a" * 64}
    monkeypatch.setattr(products_module, "is_sealed", lambda run_dir: True)

    write_products(ctx)

    assert read_cited(ctx.run_dir) == (CitedProduct("fake", "b" * 64),)


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


def _terrain_request(**overrides) -> TerrainRequest:
    facts = {
        "dem": Path("dem.tif"),
        "dem_sha256": "a" * 64,
        "state": "raw",
        "method": "fill",
        "capped_breach": None,
        "crs_project": "EPSG:2154",
        "engine": {"engine_id": "whitebox_workflows", "engine_version": "1.0"},
        "notched": False,
        "out_dir": Path("out"),
    }
    facts.update(overrides)
    return TerrainRequest(**facts)


def test_the_two_terrain_kinds_share_package_step_and_writer() -> None:
    plain = products_module.PRODUCT_KINDS["terrain"]
    notched = products_module.PRODUCT_KINDS["terrain_notched"]

    assert (plain.package, plain.step) == ("catchment", "build_geographic")
    assert (notched.package, notched.step) == ("catchment", "build_geographic")
    assert plain.write is notched.write


def test_terrain_supply_selects_the_kind_and_a_digest_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = _ctx(tmp_path)
    captured: list[tuple[str, str]] = []

    def fake_ask(ctx, kind, *, key, build, read):
        captured.append((kind, key))
        return build()

    monkeypatch.setattr(products_module, "ask", fake_ask)
    supply = terrain_supply(ctx)

    supply(_terrain_request(), build=lambda: "plain")
    supply(_terrain_request(notched=True), build=lambda: "notched")

    assert captured[0][0] == "terrain"
    assert captured[1][0] == "terrain_notched"
    assert captured[0][1] != captured[1][1]
    assert len(captured[0][1]) == 64


def test_terrain_supply_keys_what_processing_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = _ctx(tmp_path)
    captured: list[str] = []

    def fake_ask(ctx, kind, *, key, build, read):
        captured.append(key)
        return build()

    monkeypatch.setattr(products_module, "ask", fake_ask)
    supply = terrain_supply(ctx)

    supply(_terrain_request(method="fill"), build=lambda: "fill")
    supply(_terrain_request(method="breach"), build=lambda: "breach")

    assert captured[0] != captured[1]
