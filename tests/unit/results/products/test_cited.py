"""``products.json`` of a run: order, absence, schema, and the keys a run protects."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hydromodpy.results.products import cited as cited_module
from hydromodpy.results.products.cited import (
    CitedProduct,
    alive_keys,
    read_cited,
    write_cited,
)


def test_write_then_read_in_order(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "a"
    run_dir.mkdir(parents=True)
    path = write_cited(run_dir, [CitedProduct("mesh", "k1"), CitedProduct("soil", "k2")])

    assert path.name == "products.json"
    assert read_cited(run_dir) == (CitedProduct("mesh", "k1"), CitedProduct("soil", "k2"))


def test_an_absent_file_reads_empty(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "a"
    run_dir.mkdir(parents=True)
    assert read_cited(run_dir) == ()


def test_an_unknown_schema_is_refused(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "a"
    run_dir.mkdir(parents=True)
    (run_dir / "products.json").write_text(
        json.dumps({"schema": "hydromodpy.products.v0", "products": []}), encoding="utf-8"
    )

    with pytest.raises(ValueError, match="hydromodpy.products.v0"):
        read_cited(run_dir)


def test_alive_keys_reads_only_the_running_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "project"
    for name in ("running", "sealed", "failed", "dead"):
        run_dir = project / "runs" / name
        run_dir.mkdir(parents=True)
        write_cited(run_dir, [CitedProduct(name, f"{name}-key")])
    statuses = {
        "running": "running",
        "sealed": "completed",
        "failed": "failed",
        "dead": "stale",
    }
    monkeypatch.setattr(cited_module, "effective_status", lambda d: statuses[Path(d).name])

    assert alive_keys(project) == frozenset({"running-key"})


def test_alive_keys_without_runs_is_empty(tmp_path: Path) -> None:
    assert alive_keys(tmp_path / "project") == frozenset()
