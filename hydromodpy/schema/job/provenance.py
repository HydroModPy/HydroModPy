"""How one job ran: tool, commit, interpreter, platform, backend, packages.

The third document of the write order, and the only one that describes the
machine rather than the work. It answers the one question a reader of a sealed
directory cannot answer from the artefacts: *could I run this again and get
these bytes?*

Two things this document deliberately does not carry.

**No instant.** The timing lives in ``outcome.json``, which is the document
that owns status and duration. Keeping a clock out of here is also what makes
two byte-identical submissions produce two byte-identical provenance
documents, which is the property the reuse short-circuit of ``job_id`` needs:
a field that moves every run would make every job look new.

**No hostname, no user name, and no local path.** The run profile records the
first two, because a run directory lives in a workspace its owner controls. A
job directory is handed to somebody else by construction -- that is what a
capability is for -- and a sealed document published from a shared scheduler
has no business naming the account that executed it. The interpreter is named
by its version and implementation for the same reason: this document carried
``sys.executable`` for one afternoon, and on the machine it was written on
that string was ``/home/<user>/micromamba/envs/<env>/bin/python``. A path
under somebody's home directory is not reproduction information, it is an
account name and a directory layout.
"""

from __future__ import annotations

import platform
import subprocess
from importlib.metadata import distributions
from pathlib import Path
from typing import Any

from hydromodpy.core.version import __version__
from hydromodpy.schema.job.directory import JobDirectory
from hydromodpy.schema.job.documents import write_document

PROVENANCE_SCHEMA = "hmp-provenance/v1"

_GIT_TIMEOUT_S = 2
"""A provenance document is not worth blocking a job on a slow git."""

_INSTALL_ROOT = Path(__file__).resolve().parents[3]
"""Where ``git`` is asked about this build, when this build is a checkout."""


def _git(*args: str) -> str | None:
    """Return the output of one git command, or ``None`` when it cannot run.

    An installed wheel is not a checkout and a build machine may ship no git
    at all. Both are ordinary, and both are reported as an unknown commit
    rather than as a failure of the job.
    """
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=str(_INSTALL_ROOT),
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout


def git_state() -> dict[str, Any]:
    """Return the commit this build was taken from, and whether it is dirty.

    ``dirty`` is ``None`` and not ``False`` when the commit is unknown: a
    wheel that no working tree backs is not a clean checkout, it is not a
    checkout, and the two answers must not be spelled the same.
    """
    commit = _git("rev-parse", "HEAD")
    if commit is None:
        return {"commit": None, "dirty": None}
    status = _git("status", "--porcelain")
    return {
        "commit": commit.strip() or None,
        "dirty": None if status is None else bool(status.strip()),
    }


def frozen_packages() -> dict[str, str]:
    """Return every distribution importable from this interpreter, by name.

    The whole environment and not a chosen subset: the reader of a sealed
    directory is trying to rebuild it, and a list of the packages this
    repository believes it uses would leave out the transitive pin that
    actually moved the numbers.
    """
    frozen: dict[str, str] = {}
    for distribution in distributions():
        name = distribution.metadata["Name"]
        if not name:
            continue
        frozen[name] = distribution.version or ""
    return dict(sorted(frozen.items()))


def build_provenance(
    *,
    job_id: str,
    process_id: str,
    process_version: str,
    backend: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble the provenance document of one job.

    *backend* names the engine that did the work -- its id, its version and
    the digest of the build -- and is ``None`` only for a capability that runs
    on no engine at all.
    """
    return {
        "schema": PROVENANCE_SCHEMA,
        "job_id": job_id,
        "process": {"id": process_id, "version": process_version},
        "tool": {"name": "hydromodpy", "version": __version__},
        "git": git_state(),
        "python": {
            "version": platform.python_version(),
            "implementation": platform.python_implementation(),
        },
        "platform": {
            "platform": platform.platform(),
            "system": platform.system(),
            "machine": platform.machine(),
        },
        "backend": backend,
        "packages": frozen_packages(),
    }


def write_provenance(job: JobDirectory, document: dict[str, Any]) -> Path:
    """Write *document* as ``provenance.json`` of *job*."""
    return write_document(job.provenance_path, document)


__all__ = [
    "PROVENANCE_SCHEMA",
    "build_provenance",
    "frozen_packages",
    "git_state",
    "write_provenance",
]
