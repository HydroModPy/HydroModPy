from __future__ import annotations
import os,sys,time
from dataclasses import dataclass,field
from typing import Any
@dataclass(slots=True)
class RuntimeMetrics:
    pid: int = field(default_factory=os.getpid)
    ppid: int | None = None
    process_name: str | None = None
    command_line: list[str] = field(default_factory=list)
    working_directory: str | None = None
    environment: dict[str, str] = field(default_factory=dict)
    uptime_seconds: float | None = None
    elapsed_seconds: float | None = None
    logs: list[str]= field (default_factory=list)
    exception_type: str | None = None
    exception_message: str | None = None
    exception_traceback: str | None = None

class RuntimeProbe:
    @staticmethod
    def collect_start(start_time: float, *, env_keys: list[str] | None = None) -> RuntimeMetrics:
            env_keys = env_keys or [
                "HMP_WORKSPACE",
                "PYTHONPATH",
                "CONDA_DEFAULT_ENV",
                "VIRTUAL_ENV",
                "CUDA_VISIBLE_DEVICES",
                "OMP_NUM_THREADS",
            ]
            return RuntimeMetrics(
                pid=os.getpid(),
                ppid=os.getppid(),
                process_name=os.path.basename(sys.executable),
                command_line=list(sys.argv),
                working_directory=os.getcwd(),
                environment={key: os.environ.get(key, "") for key in env_keys},
                uptime_seconds=max(0.0, time.time() - start_time),
            )

    @staticmethod
    def collect_end(start_time: float) -> RuntimeMetrics:
            return RuntimeMetrics(
                pid=os.getpid(),
                elapsed_seconds=max(0.0, time.time() - start_time),
            )