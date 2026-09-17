"""The capabilities this build can be invoked as, and how to drive one.

A capability is declared in the layer that implements it, and the exit-code
mapper lives here in ``cli``. Nothing below ``cli`` can see both, so this is
where the two meet: the registry pairs one declaration with one runner, and
the verbs of ``hmp process`` read it.

It is a Python mapping and not a resource directory. The published process
**descriptions** are resource files under ``hydromodpy/schema/processes/``,
read with ``importlib.resources``: a different object, generated from the
declarations named here by ``python -m tools.processes``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

from hydromodpy.core.exceptions import JobUsageError
from hydromodpy.core.interrupts import terminate_as_interrupt
from hydromodpy.schema.capability import CapabilityDecl
from hydromodpy.schema.job.directory import JobDirectory
from hydromodpy.schema.job.outcome import JobOutcome
from hydromodpy.schema.job.seal import SealVerification, verify_job

CapabilityRunner = Callable[..., JobOutcome]
"""``run(job, *, exit_code_for)``, the one shape a capability body has."""


@dataclass(frozen=True, slots=True)
class Capability:
    """One declaration and the function that executes it."""

    decl: CapabilityDecl
    run: CapabilityRunner


def capability_decls() -> tuple[CapabilityDecl, ...]:
    """Return every declaration, without importing a single engine.

    A declaration is what the process description is generated from and what
    ``hmp process list`` prints; neither needs the body to exist in memory.
    Kept apart from :func:`_registry` because importing a body pulls its whole
    engine stack in -- ``whitebox_workflows`` for this one -- and a test pins
    the two lists together so they cannot drift.
    """
    from hydromodpy.spatial.site_selection.hydrology.capability import TERRAIN_DELINEATE

    return (TERRAIN_DELINEATE,)


def _registry() -> Mapping[str, Capability]:
    """Build the registry, importing each worker only when it is asked for."""
    from hydromodpy.spatial.site_selection.hydrology.worker import run as terrain_delineate

    runners: Mapping[str, CapabilityRunner] = {"terrain-delineate": terrain_delineate}
    return MappingProxyType(
        {decl.id: Capability(decl=decl, run=runners[decl.id]) for decl in capability_decls()}
    )


def capability_ids() -> tuple[str, ...]:
    """Return every capability id this build serves, sorted."""
    return tuple(sorted(decl.id for decl in capability_decls()))


def capability(capability_id: str) -> Capability:
    """Return one capability, refusing an id nobody serves.

    :class:`JobUsageError` and not a refused document: the id comes from the
    command line, so getting it wrong is an invocation mistake, which is the
    one failure a shim must be able to tell apart from the job failing.
    """
    registry = _registry()
    try:
        return registry[capability_id]
    except KeyError as exc:
        served = ", ".join(sorted(registry)) or "none"
        raise JobUsageError(
            f"no capability named {capability_id!r}; this build serves {served}"
        ) from exc


def list_capabilities() -> list[dict[str, Any]]:
    """Return one record per capability, in the shape a shim indexes."""
    return [
        {
            "id": decl.id,
            "version": decl.version,
            "major": decl.major,
            "title": decl.title,
            "keywords": list(decl.keywords),
            "outputs": list(decl.output_ids),
        }
        for decl in sorted(capability_decls(), key=lambda decl: decl.id)
    ]


def describe_capability(capability_id: str, major: int | None = None) -> str:
    """Return the exact bytes of one process description.

    Read from package data and not rendered here: the description is generated
    from the declaration, committed, and gated against the generator. Rendering
    it a second time in this function would be a second source of truth, and
    the one a caller reads would be the one nothing compares.
    """
    from hydromodpy.schema.processes import read_description_text

    return read_description_text(capability_id, major)


def run_capability(capability_id: str, job_dir: str | Path) -> tuple[int, str]:
    """Run one capability in one job directory.

    Returns the exit code and the **bytes** the process puts on stdout, read
    back from ``outcome.json`` rather than re-rendered: the promise is that a
    caller who captured the pipe and a caller who opens the directory learn
    the same thing, and the only way to keep it is to print the file.

    SIGTERM unwinds through :func:`terminate_as_interrupt`, so a cancelled job
    writes its dismissed outcome and exits 130 with nothing sealed.
    """
    from hydromodpy.cli.helpers import EXIT_SIGINT, exit_code_for

    # The handler goes on **before** the registry is touched, not around the
    # run alone. Resolving the capability imports its whole engine stack, which
    # is most of the wall time of a small job; a SIGTERM inside that window used
    # to kill the process at 143 with an empty stdout and no outcome at all.
    with terminate_as_interrupt():
        entry = capability(capability_id)
        job = JobDirectory.open(job_dir)
        try:
            outcome = entry.run(job, exit_code_for=exit_code_for)
        except KeyboardInterrupt:
            return EXIT_SIGINT, _outcome_text(job)
    return outcome.exit_code, _outcome_text(job)


def _outcome_text(job: JobDirectory) -> str:
    """The exact bytes of ``outcome.json``, or nothing when it is absent."""
    if not job.outcome_path.is_file():
        return ""
    return job.outcome_path.read_text(encoding="utf-8")


def verify_capability_job(job_dir: str | Path) -> SealVerification:
    """Re-check a finished job directory against its own seal.

    Opened for reading and not through :meth:`JobDirectory.open`, which
    requires ``request.json``: a truncated transfer that lost exactly that
    file is the case this verb exists for, and it must be reported, not
    answered with "you invoked me wrong".
    """
    return verify_job(JobDirectory.for_reading(job_dir))


__all__ = [
    "Capability",
    "CapabilityRunner",
    "capability",
    "capability_decls",
    "capability_ids",
    "describe_capability",
    "list_capabilities",
    "run_capability",
    "verify_capability_job",
]
