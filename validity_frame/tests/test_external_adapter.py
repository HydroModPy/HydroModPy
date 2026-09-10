from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from validity_frame.auto_capture.collector import AutoCaptureCollector
from validity_frame.auto_capture.context import ExecutionContext


def test_auto_capture_collector_returns_snapshots(tmp_path: Path):
    ctx = ExecutionContext(run_id="test_run", workspace=str(tmp_path))
    cap = AutoCaptureCollector(context=ctx)

    start_snapshot = cap.capture_start()
    end_snapshot = cap.capture_end(
        start_time=0.0,
        solver_source=SimpleNamespace(
            solver_name="fake",
            iterations=1,
            converged=True,
            status="ok",
        ),
    )

    assert start_snapshot.execution.run_id == "test_run"
    assert end_snapshot.status == "completed"
    assert end_snapshot.solver.solver_name == "fake"
