"""Wiring tests for ``hmp catalog rerun`` (provider mocked; no real solve)."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

import hydromodpy
from hydromodpy.cli._workers.catalog import rerun_simulation
from hydromodpy.cli.commands.catalog import rerun as rerun_cmd
from hydromodpy.results.catalog import Catalog
from hydromodpy.results.run import rerun_contract


@pytest.fixture
def restore_provider():
    hydromodpy.bootstrap()
    original = rerun_contract._provider
    try:
        yield
    finally:
        rerun_contract.register_rerun_provider(original)


def test_parse_overrides_coerces_types() -> None:
    assert rerun_cmd._parse_overrides(["flow.K=2e-4", "sim.flag=true", "n=5"]) == {
        "flow.K": 2e-4,
        "sim.flag": True,
        "n": 5,
    }


def test_rerun_reads_snapshot_and_forwards_overrides(tmp_path: Path, restore_provider) -> None:
    calls: dict = {}

    class MockProvider:
        def rerun(self, snapshot, *, overrides, name, source_sim_id=None):
            calls.update(overrides=dict(overrides), name=name, keys=sorted(snapshot))
            return "11111111-2222-3333-4444-555555555555"

    rerun_contract.register_rerun_provider(MockProvider())

    sid = str(uuid.uuid4())
    with Catalog(tmp_path) as catalog:
        catalog.register_simulation(
            sid,
            project="cheze",
            solver="modflow6",
            name="baseline",
            config={"flow": {"k": 1e-4}},
            config_snapshot={"workspace": {"root": str(tmp_path)}, "flow": {"k": 1e-4}},
        )

    result = rerun_simulation("baseline", workspace=tmp_path, overrides={"flow.k": 2e-4}, name=None)
    assert result["sim_id"] == "11111111-2222-3333-4444-555555555555"
    assert result["name"] == "baseline_rerun"
    assert calls["overrides"] == {"flow.k": 2e-4}
    assert calls["keys"] == ["flow", "workspace"]


def test_rerun_without_snapshot_raises(tmp_path: Path, restore_provider) -> None:
    sid = str(uuid.uuid4())
    with Catalog(tmp_path) as catalog:
        catalog.register_simulation(sid, project="cheze", solver="modflow6", name="nosnap")
    with pytest.raises(ValueError, match="no config snapshot"):
        rerun_simulation("nosnap", workspace=tmp_path, overrides={}, name=None)
