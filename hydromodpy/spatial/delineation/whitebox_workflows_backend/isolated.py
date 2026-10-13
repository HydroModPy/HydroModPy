"""Whitebox depression removal, run in a child interpreter.

Whitebox Workflows 1.3.5 removes depressions on worker threads and takes the
raster back with ``Arc::try_unwrap`` as soon as the last row arrives. A worker
that has sent its row but not yet dropped its handle makes that call fail, and
the tool panics: ``Error unwrapping 'output'`` at
``src/tools/hydrology/fill_depressions.rs:191``. Every Whitebox tool installs a
panic hook that calls ``process::exit(1)``, so the panic ends the interpreter
that called the tool, with no Python exception and no traceback. One worker
does not avoid it: ``fill_depressions`` lost the race once in 700 to 6 400
calls on an idle machine, and more often on a loaded one.

The two tools that carry this code, ``fill_depressions`` and
``breach_depressions_least_cost``, therefore run in a child interpreter. The
tool is deterministic on one worker, so a child that died of that race is run
again, and the warning says so. Any other failure is raised with the child's
own message.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from hydromodpy.core.exceptions import TerrainError
from hydromodpy.core.logging import get_logger

logger = get_logger(__name__)

DEPRESSION_TOOLS = frozenset({"fill_depressions", "breach_depressions_least_cost"})
"""The Whitebox tools that take their raster back with ``Arc::try_unwrap``."""

RACE_SIGNATURE = "Error unwrapping 'output'"
"""What Whitebox prints to stderr when it loses the race, and nothing else does."""

MAX_ATTEMPTS = 3
"""Children run for one call before its failure is raised."""

_CHILD = Path(__file__).with_name("_depression_child.py")


def run_depression_tool(
    env: Any,
    tool: str,
    dem: Any,
    *,
    options: Mapping[str, object],
    max_procs: int,
    verbose: bool,
) -> Any:
    """Run *tool* on *dem* in a child interpreter and return its raster.

    *env* is the caller's ``WbEnvironment``. It writes *dem* for the child and
    reads the child's result back, which is exact: a Whitebox raster stores its
    cells in the type it writes.
    """
    if tool not in DEPRESSION_TOOLS:
        raise ValueError(f"{tool!r} is not a Whitebox depression tool: {sorted(DEPRESSION_TOOLS)}")
    with tempfile.TemporaryDirectory(prefix="hmp-wbw-") as scratch:
        source = Path(scratch) / "source.tif"
        target = Path(scratch) / "result.tif"
        env.write_raster(dem, str(source), compress=False)
        command = [
            sys.executable,
            "-P",
            str(_CHILD),
            tool,
            str(source),
            str(target),
            json.dumps(dict(options)),
            str(int(max_procs)),
            "1" if verbose else "0",
        ]
        attempt = 1
        while True:
            completed = subprocess.run(
                command, capture_output=True, text=True, errors="replace", check=False
            )
            if verbose and completed.stdout:
                sys.stdout.write(completed.stdout)
            if completed.returncode == 0:
                return env.read_raster(str(target))
            stderr = completed.stderr.strip()
            if RACE_SIGNATURE not in stderr or attempt == MAX_ATTEMPTS:
                raise TerrainError(
                    f"Whitebox {tool} failed in its child process "
                    f"(exit code {completed.returncode}, attempt {attempt} of "
                    f"{MAX_ATTEMPTS}): {stderr or 'no message on stderr'}"
                )
            logger.warning(
                "Whitebox %s lost the thread race of whitebox-workflows 1.3.5 "
                "(attempt %d of %d); the child is run again. Whitebox said: %s",
                tool,
                attempt,
                MAX_ATTEMPTS,
                stderr,
            )
            attempt += 1


__all__ = ["DEPRESSION_TOOLS", "MAX_ATTEMPTS", "RACE_SIGNATURE", "run_depression_tool"]
