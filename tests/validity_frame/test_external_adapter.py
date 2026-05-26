from __future__ import annotations

import json
from pathlib import Path

from hydromodpy.validity_frame.auto_capture import RuntimeAutoCapture, ExecutionContext
from hydromodpy.validity_frame.probes.base import ProbeProtocol


class FakeProbe:
    def __init__(self):
        self.started = False

    def role(self) -> str:
        return "solver"

    def collect(self, source=None):
        return {"solver_name": "fake", "iterations": 1, "converged": True}


def test_runtime_capture_writes_snapshot(tmp_path: Path):
    ctx = ExecutionContext(run_id="test_run", workspace=str(tmp_path))
    probe = FakeProbe()
    assert isinstance(probe, ProbeProtocol)
    cap = RuntimeAutoCapture(context=ctx, probes={"solver": probe}, output_dir=tmp_path / "raw")

    def work():
        return 42

    result, snapshot = cap.run_with_capture(work)
    assert result == 42

    # verify files were written
    raw_dir = tmp_path / "raw"
    assert raw_dir.exists()
    success_file = raw_dir / "runtime_capture_success.json"
    assert success_file.exists()
    data = json.loads(success_file.read_text(encoding="utf-8"))
    assert data.get("solver") is not None
    assert data.get("status") == "completed"
