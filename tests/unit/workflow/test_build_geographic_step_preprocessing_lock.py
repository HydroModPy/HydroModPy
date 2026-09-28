"""D13: BuildGeographicStep and BuildMeshStep must serialize on the shared
.hmp/scratch/_preprocessing/ tree across concurrent runs of one project.

Four ``hmp run`` started seconds apart in the same project folder used to
die inside ``build_geographic`` with half-written or already-vanished
preprocessing files (a Whitebox panic, a missing ``dem_fill.tif``, a missing
``outlet.shp``): every run wrote and read the same per-project scratch tree
with no coordination. These tests race two threads through the real step
code, with the heavy internals stubbed out, and check the lock actually
keeps them from overlapping.
"""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import hydromodpy.workflow.steps.mesh as mesh_steps
import hydromodpy.workflow.steps.setup as setup_steps
from hydromodpy.workflow.internals.state import PipelineState
from hydromodpy.workflow.steps.mesh import BuildMeshStep
from hydromodpy.workflow.steps.setup import BuildGeographicStep


def _assert_never_overlapped(events: list[tuple[str, str]]) -> None:
    assert len(events) == 4
    for index in range(0, len(events), 2):
        enter_kind, enter_thread = events[index]
        exit_kind, exit_thread = events[index + 1]
        assert enter_kind == "enter"
        assert exit_kind == "exit"
        assert exit_thread == enter_thread, (
            f"another thread entered before {enter_thread} left: {events}"
        )


def test_build_geographic_step_serializes_concurrent_project_runs(tmp_path, monkeypatch) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()

    events: list[tuple[str, str]] = []
    events_lock = threading.Lock()

    def fake_step_setup(_ctx, **_kwargs):
        with events_lock:
            events.append(("enter", threading.current_thread().name))
        time.sleep(0.1)
        with events_lock:
            events.append(("exit", threading.current_thread().name))

    monkeypatch.setattr(setup_steps, "step_setup", fake_step_setup)
    monkeypatch.setattr(setup_steps, "step_spatial_supports", lambda *_a, **_k: None)

    def run_once(name: str) -> None:
        ctx = SimpleNamespace(
            cfg=SimpleNamespace(workspace=SimpleNamespace(project_root=project_root))
        )
        state = PipelineState(run_id=name, step_index=0, data={"ctx": ctx})
        BuildGeographicStep()._build(state, reuse_existing_outputs=None)

    threads = [
        threading.Thread(target=run_once, args=(f"run-{i}",), name=f"run-{i}") for i in range(2)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    _assert_never_overlapped(events)


def test_build_mesh_step_serializes_concurrent_project_runs(tmp_path, monkeypatch) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()

    events: list[tuple[str, str]] = []
    events_lock = threading.Lock()

    def fake_step_mesh(_ctx, **_kwargs):
        with events_lock:
            events.append(("enter", threading.current_thread().name))
        time.sleep(0.1)
        with events_lock:
            events.append(("exit", threading.current_thread().name))

    monkeypatch.setattr(mesh_steps, "step_mesh", fake_step_mesh)
    monkeypatch.setattr(mesh_steps, "step_mesh_input", lambda *_a, **_k: None)
    monkeypatch.setattr(setup_steps, "step_spatial_supports", lambda *_a, **_k: None)

    def run_once(name: str) -> None:
        workspace = SimpleNamespace(project_root=project_root)
        ctx = SimpleNamespace(
            cfg=SimpleNamespace(workspace=SimpleNamespace(project_root=project_root)),
            setup=SimpleNamespace(workspace=workspace),
        )
        state = PipelineState(run_id=name, step_index=0, data={"ctx": ctx})
        BuildMeshStep().run(state)

    threads = [
        threading.Thread(target=run_once, args=(f"run-{i}",), name=f"run-{i}") for i in range(2)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    _assert_never_overlapped(events)
