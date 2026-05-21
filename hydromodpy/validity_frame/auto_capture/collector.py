from __future__ import annotations

import traceback
from dataclasses import dataclass, field
from typing import Any

from hydromodpy.validity_frame.auto_capture.context import ExecutionContext
from hydromodpy.validity_frame.probes.hardware import HardwareMetrics, HardwareProbe
from hydromodpy.validity_frame.probes.runtime import RuntimeMetrics, RuntimeProbe
from hydromodpy.validity_frame.probes.solver import SolverMetrics, SolverProbe
from hydromodpy.validity_frame.probes.system import SystemMetrics, SystemProbe


@dataclass(slots=True)
class AutoCaptureSnapshot:
    execution: ExecutionContext
    system: SystemMetrics
    hardware: HardwareMetrics
    runtime: RuntimeMetrics
    solver: SolverMetrics
    status: str = "running"
    logs: list[str] = field(default_factory=list)
    exception: dict[str, str] | None = None


class AutoCaptureCollector:
    def __init__(self, context: ExecutionContext | None = None) -> None:
        self.context = context or ExecutionContext()

    def capture_start(self) -> AutoCaptureSnapshot:
        import time

        start_time = time.time()
        return AutoCaptureSnapshot(
            execution=self.context,
            system=SystemProbe.collect(),
            hardware=HardwareProbe.collect(),
            runtime=RuntimeProbe.collect_start(start_time),
            solver=SolverProbe.collect(),
        )

    def capture_end(
        self,
        *,
        start_time: float,
        solver_source: Any = None,
        logs: list[str] | None = None,
    ) -> AutoCaptureSnapshot:
        snapshot = AutoCaptureSnapshot(
            execution=self.context,
            system=SystemProbe.collect(),
            hardware=HardwareProbe.collect(),
            runtime=RuntimeProbe.collect_end(start_time),
            solver=SolverProbe.collect(solver_source),
            status="completed",
            logs=logs or [],
        )
        return snapshot

    def capture_exception(
        self,
        *,
        start_time: float,
        exc: BaseException,
        solver_source: Any = None,
        logs: list[str] | None = None,
    ) -> AutoCaptureSnapshot:
        snapshot = AutoCaptureSnapshot(
            execution=self.context,
            system=SystemProbe.collect(),
            hardware=HardwareProbe.collect(),
            runtime=RuntimeProbe.collect_end(start_time),
            solver=SolverProbe.collect(solver_source),
            status="failed",
            logs=logs or [],
            exception={
                "type": type(exc).__name__,
                "message": str(exc),
                "traceback": "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
            },
        )
        return snapshot
