"""Execution backends for external comparison child simulations."""

from __future__ import annotations

import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

_SIM_ID_RE = re.compile(
    r"\bsim_id\s*:\s*([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12})\b"
)


@dataclass(frozen=True, slots=True)
class ChildRunResult:
    """Result of one externally launched child simulation."""

    config_path: Path
    returncode: int
    wall_time_seconds: float
    sim_id: str | None
    stdout: str
    stderr: str

    @property
    def succeeded(self) -> bool:
        return self.returncode == 0


def parse_sim_id_from_output(stdout: str, stderr: str) -> str | None:
    """Extract the sim_id printed by ``hmp run`` summary output."""
    text = f"{stdout}\n{stderr}"
    match = _SIM_ID_RE.search(text)
    return None if match is None else match.group(1).lower()


def run_child_with_hmp(
    config_path: Path,
    *,
    python_executable: str | None = None,
    timeout_seconds: float | None = None,
) -> ChildRunResult:
    """Run one child TOML through the public CLI entry point."""
    executable = python_executable or sys.executable
    command = [
        executable,
        "-m",
        "hydromodpy._cli.main",
        "run",
        str(config_path),
    ]
    start = time.monotonic()
    completed = subprocess.run(
        command,
        cwd=str(config_path.parent),
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
    )
    wall_time_seconds = time.monotonic() - start
    return ChildRunResult(
        config_path=config_path,
        returncode=int(completed.returncode),
        wall_time_seconds=wall_time_seconds,
        sim_id=parse_sim_id_from_output(completed.stdout, completed.stderr),
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


__all__ = (
    "ChildRunResult",
    "parse_sim_id_from_output",
    "run_child_with_hmp",
)
