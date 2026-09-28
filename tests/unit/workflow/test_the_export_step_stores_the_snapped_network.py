"""The export step stores the snapped mapped network when the snap is on, and only then.

It runs inside the scope that holds the store, before the seal, so the stored
map is part of the sealed run.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import hydromodpy.results.derive.snapped_network as snapped_network
import hydromodpy.workflow.steps.export as export_module
from hydromodpy.core.stream_snap import SnapStreamsConfig
from hydromodpy.results.run import Run


def _ctx(mode: str | None, *, sim_id: str | None = "sim-1") -> SimpleNamespace:
    geographic = (
        None if mode is None else SimpleNamespace(snap_streams=SnapStreamsConfig(mode=mode))
    )
    return SimpleNamespace(
        cfg=SimpleNamespace(
            geographic=geographic,
            analysis=SimpleNamespace(capability_gallery=SimpleNamespace(enabled=False)),
        ),
        sim_id=sim_id,
    )


@pytest.fixture
def persisted(monkeypatch) -> list[tuple[object, object]]:
    calls: list[tuple[object, object]] = []

    def record(run: object, store: object) -> tuple[str, ...]:
        calls.append((run, store))
        return ("maximal",)

    monkeypatch.setattr(snapped_network, "persist_snapped_networks", record)
    return calls


@pytest.mark.parametrize("mode", ["diagnose", "apply"])
def test_a_run_whose_snap_is_on_stores_its_snapped_map(mode: str, persisted) -> None:
    store = SimpleNamespace()

    export_module.step_save_snapped_network(_ctx(mode), store=store)

    assert len(persisted) == 1
    run, used = persisted[0]
    assert isinstance(run, Run)
    assert run.sim_id == "sim-1"
    assert used is store


@pytest.mark.parametrize("mode", [None, "off"])
def test_a_run_whose_snap_is_off_stores_nothing(mode: str | None, persisted) -> None:
    export_module.step_save_snapped_network(_ctx(mode), store=SimpleNamespace())

    assert persisted == []


def test_an_unregistered_run_stores_nothing(persisted) -> None:
    export_module.step_save_snapped_network(_ctx("apply", sim_id=None), store=SimpleNamespace())

    assert persisted == []


def test_saving_the_run_artifacts_stores_the_snapped_map(persisted) -> None:
    store = SimpleNamespace()

    export_module.step_save_run_artifacts(_ctx("diagnose"), 0.0, store=store)

    assert [used for _, used in persisted] == [store]
