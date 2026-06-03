from __future__ import annotations

import platform
from dataclasses import dataclass


@dataclass(slots=True)
class SystemMetrics:
    os_name: str | None = None
    os_release: str | None = None
    os_version: str | None = None
    machine: str | None = None
    python_version: str | None = None


class SystemProbe:
    @staticmethod
    def collect() -> SystemMetrics:
        return SystemMetrics(
            os_name=platform.system(),
            os_release=platform.release(),
            os_version=platform.version(),
            machine=platform.machine(),
            python_version=platform.python_version(),
        )

    @staticmethod
    def capture() -> SystemMetrics:
        return SystemProbe.collect()
