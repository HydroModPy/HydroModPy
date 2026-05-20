from __future__ import annotations
import json
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from hydromodpy.validity_frame.auto_capture.collector import AutoCaptureCollector
from hydromodpy.validity_frame.auto_capture.context import ExecutionContext

class RuntimeAutoCapture:
    def __init__(
        self,
        *,
        context: ExecutionContext | None = None,
        output_dir: str | Path | None = None,
    ) -> None:
        self.collector = AutoCaptureCollector(context)
        self.output_dir = Path(output_dir).expanduser().resolve() if output_dir is not None else None

    def _write_snapshot(self, name: str, payload: dict[str, Any]) -> Path | None:
        if self.output_dir is None:
            return None
        self.output_dir.mkdir(parents=True, exist_ok=True)
        path = self.output_dir / name
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        return path

    @contextmanager
    def track(
        self,
        *,
        solver_source: Any = None,
        logs: list[str] | None = None,
    ) -> Iterator[dict[str, Any]]:
        start_time = time.time()
        start_snapshot = self.collector.capture_start()
        yield {
            "start": start_snapshot,
            "start_time": start_time,
        }
        end_snapshot = self.collector.capture_end(
            start_time=start_time,
            solver_source=solver_source,
            logs=logs,
        )
        self._write_snapshot("runtime_capture_end.json", end_snapshot.__dict__)

    def run_with_capture(self, func, *, solver_source: Any = None, logs: list[str] | None = None):
        start_time = time.time()
        try:
            result = func()
            snapshot = self.collector.capture_end(
                start_time=start_time,
                solver_source=solver_source,
                logs=logs,
            )
            self._write_snapshot("runtime_capture_success.json", snapshot.__dict__)
            return result, snapshot
        except BaseException as exc:
            snapshot = self.collector.capture_exception(
                start_time=start_time,
                exc=exc,
                solver_source=solver_source,
                logs=logs,
            )
            self._write_snapshot("runtime_capture_failure.json", snapshot.__dict__)
            raise