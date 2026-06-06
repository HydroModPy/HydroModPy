"""Resolved run manifest persistence contracts."""

from __future__ import annotations

import json
import os
from pathlib import Path

from hydromodpy.workflow.internals.manifest import ResolvedRunManifest
from hydromodpy.workflow.internals.state import PipelineState


class _Step:
    name = "prepare"


def test_manifest_write_atomic_retries_transient_permission_error(
    tmp_path: Path,
    monkeypatch,
) -> None:
    manifest = ResolvedRunManifest.from_state(
        PipelineState(run_id="run-1", data={"raw_toml": {"simulation": {"name": "demo"}}}),
        [_Step()],
        tmp_path,
    )
    original_replace = os.replace
    calls = {"count": 0}

    def flaky_replace(source, target):
        calls["count"] += 1
        if calls["count"] == 1:
            raise PermissionError("transient lock")
        original_replace(source, target)

    monkeypatch.setattr("hydromodpy.core.io.atomic.os.name", "nt")
    monkeypatch.setattr("hydromodpy.core.io.atomic.os.replace", flaky_replace)
    monkeypatch.setattr("hydromodpy.core.io.atomic.time.sleep", lambda _: None)

    path = manifest.write_atomic(tmp_path)

    assert calls["count"] == 2
    assert path.is_file()
    assert json.loads(path.read_text(encoding="utf-8"))["run_id"] == "run-1"
    assert not list(path.parent.glob(".resolved_manifest.json.tmp.*"))
