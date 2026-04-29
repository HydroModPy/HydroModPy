"""Lightweight optional tracing for long-running mesh workflows."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path


def trace_mesh_stage(stage: str, **fields: object) -> None:
    """Append one timestamped stage marker when tracing is enabled.

    Tracing is activated only when ``HYDROMODPY_MESH_TRACE_FILE`` is defined.
    The helper is intentionally tiny and side-effect free when disabled so it
    can remain in production code without affecting normal runs.
    """

    trace_path_raw = os.environ.get("HYDROMODPY_MESH_TRACE_FILE", "").strip()
    if trace_path_raw == "":
        return

    trace_path = Path(trace_path_raw).expanduser()
    trace_path.parent.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().isoformat(timespec="seconds")
    payload = [f"{key}={value}" for key, value in fields.items()]
    line = f"{timestamp} | {stage}"
    if payload:
        line = f"{line} | " + " | ".join(payload)
    with trace_path.open("a", encoding="utf-8") as stream:
        stream.write(f"{line}\n")


__all__ = ["trace_mesh_stage"]
