from __future__ import annotations

import traceback
from dataclasses import dataclass, field
from typing import Any

from .context import ExecutionContext


@dataclass(slots=True)
class AutoCaptureSnapshot:
    execution: ExecutionContext
    system: Any
    hardware: Any
    runtime: Any
    solver: Any
    status: str = "running"
    logs: list[str] = field(default_factory=list)
    exception: dict[str, str] | None = None


class AutoCaptureCollector:
    """Collector that uses a set of probes. Probes can be injected as a
    mapping with keys: 'system','hardware','runtime','solver'. If none are
    provided, fallback to the builtin probes.
    """

    def __init__(
        self, context: ExecutionContext | None = None, probes: dict[str, Any] | None = None
    ) -> None:
        self.context = context or ExecutionContext()
        if probes is None:
            # lazy import to avoid import-time coupling
            from ..probes.hardware import HardwareProbe
            from ..probes.runtime import RuntimeProbe
            from ..probes.solver import SolverProbe
            from ..probes.system import SystemProbe

            self.probes = {
                "system": SystemProbe,
                "hardware": HardwareProbe,
                "runtime": RuntimeProbe,
                "solver": SolverProbe,
            }
        else:
            self.probes = probes

    def _call_probe(self, probe_key: str, method: str, *args, **kwargs):
        probe = self.probes.get(probe_key)
        if probe is None:
            return None
        fn = getattr(probe, method, None)
        if fn is None:
            # Try fallback to a generic collect
            fn = getattr(probe, "collect", None)
        if fn is None:
            return None
        return fn(*args, **kwargs)

    def capture_start(self) -> AutoCaptureSnapshot:
        import time

        start_time = time.time()
        return AutoCaptureSnapshot(
            execution=self.context,
            system=self._call_probe("system", "collect"),
            hardware=self._call_probe("hardware", "collect"),
            runtime=self._call_probe("runtime", "collect_start", start_time),
            solver=self._call_probe("solver", "collect"),
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
            system=self._call_probe("system", "collect"),
            hardware=self._call_probe("hardware", "collect"),
            runtime=self._call_probe("runtime", "collect_end", start_time),
            solver=self._call_probe("solver", "collect", solver_source),
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
            system=self._call_probe("system", "collect"),
            hardware=self._call_probe("hardware", "collect"),
            runtime=self._call_probe("runtime", "collect_end", start_time),
            solver=self._call_probe("solver", "collect", solver_source),
            status="failed",
            logs=logs or [],
            exception={
                "type": type(exc).__name__,
                "message": str(exc),
                "traceback": "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
            },
        )
        return snapshot
