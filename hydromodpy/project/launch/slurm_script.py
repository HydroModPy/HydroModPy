"""The text of the SLURM scripts: ``#SBATCH`` directives, walltime, worker block.

Why
---
:func:`hydromodpy.project.launch.slurm.write_slurm_array` fills the frozen
shell templates of :mod:`hydromodpy.project.launch.templates`; the pure text
work (a partition and a walltime checked, a template rendered) lives here.
"""

from __future__ import annotations

import re
import shlex
from collections.abc import Mapping, Sequence
from importlib import resources
from typing import Final

from hydromodpy.core.exceptions import ConfigError

TERM_GRACE_S: Final[int] = 600
"""Seconds between the scheduler's SIGTERM and the walltime."""

_PARTITION = re.compile(r"^[A-Za-z0-9_.,-]+$")
_WALLTIME = re.compile(r"^(?:(\d+)-)?(\d+)(?::(\d+))?(?::(\d+))?$")
_PLACEHOLDER = re.compile(r"\{\{[A-Z_]+\}\}")
_TEMPLATES = "hydromodpy.project.launch.templates"


def directives(partition: str | None, walltime: str | None) -> str:
    lines: list[str] = []
    if partition is not None:
        if not _PARTITION.match(partition):
            raise ConfigError(f"partition {partition!r} is not a SLURM partition name")
        lines.append(f"#SBATCH --partition={partition}")
    if walltime is not None:
        seconds = walltime_seconds(walltime)
        if seconds <= TERM_GRACE_S:
            raise ConfigError(
                f"walltime {walltime} is {seconds} s; the scheduler warns a case "
                f"{TERM_GRACE_S} s before it, so a case would be stopped at its start"
            )
        lines.append(f"#SBATCH --time={walltime}")
    return "\n".join(lines)


def walltime_seconds(walltime: str) -> int:
    """Return the seconds of a SLURM ``--time`` value.

    Forms: ``M``, ``M:S``, ``H:M:S``, ``D-H``, ``D-H:M``, ``D-H:M:S``.
    """
    match = _WALLTIME.match(walltime.strip())
    if match is None:
        raise ConfigError(f"walltime {walltime!r} is not a SLURM time (M, M:S, H:M:S, D-H:M:S)")
    days, first, second, third = match.groups()
    if days is None:
        parts = [int(p) for p in (first, second, third) if p is not None]
        if len(parts) == 1:
            return parts[0] * 60
        if len(parts) == 2:
            return parts[0] * 60 + parts[1]
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    hours = int(first)
    minutes = int(second) if second is not None else 0
    seconds = int(third) if third is not None else 0
    return int(days) * 86400 + hours * 3600 + minutes * 60 + seconds


def render(name: str, values: Mapping[str, str]) -> str:
    text = resources.files(_TEMPLATES).joinpath(name).read_text(encoding="utf-8")
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", value)
    leftover = _PLACEHOLDER.search(text)
    if leftover is not None:
        raise RuntimeError(f"template {name} keeps {leftover.group(0)} unfilled")
    return text


def worker_block(phase: str, environment_flags: Sequence[str] = ()) -> str:
    """Return the worker script of one phase with *environment_flags* on its line.

    Each flag is written quoted for bash inside the array assignment the
    template carries, so a value holding a dollar, a quote or a space crosses
    the render as one flag and nothing the shell would read.
    """
    log_prefix = "prepare" if phase == "prepare" else "array"
    return render(
        "worker.sh",
        {
            "LOG_PREFIX": log_prefix,
            "PHASE": phase,
            "TERM_GRACE_S": str(TERM_GRACE_S),
            "ENVIRONMENT_FLAGS": " ".join(shlex.quote(str(flag)) for flag in environment_flags),
        },
    )


__all__ = ["TERM_GRACE_S", "directives", "render", "walltime_seconds", "worker_block"]
