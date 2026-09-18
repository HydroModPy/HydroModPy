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

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

from hydromodpy.core.exceptions import JobUsageError
from hydromodpy.core.interrupts import terminate_as_interrupt
from hydromodpy.schema.capability import CapabilityDecl
from hydromodpy.schema.job.directory import JobDirectory
from hydromodpy.schema.job.outcome import DISMISSED_STATUS, JobOutcome
from hydromodpy.schema.job.reuse import reused_outcome_text
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
    engine stack in -- ``whitebox_workflows`` for one, geopandas, xarray and
    pyarrow for the other.
    """
    from hydromodpy.data.fetch.capability import DATA_FETCH
    from hydromodpy.spatial.site_selection.hydrology.capability import TERRAIN_DELINEATE

    return (DATA_FETCH, TERRAIN_DELINEATE)


def _registry() -> Mapping[str, Capability]:
    """Build the registry, importing each worker only when it is asked for.

    A declaration without a body is a build defect and says so. The lookup used
    to be a bare subscript, so a declaration renamed on one side alone raised
    ``KeyError`` out of the comprehension -- before :func:`capability` could turn
    an unknown id into a usage error, and for *every* capability rather than the
    renamed one, mapped to the generic exit 1.
    """
    from hydromodpy.data.fetch.worker import run as data_fetch
    from hydromodpy.spatial.site_selection.hydrology.worker import run as terrain_delineate

    runners: Mapping[str, CapabilityRunner] = {
        "data-fetch": data_fetch,
        "terrain-delineate": terrain_delineate,
    }
    served: dict[str, Capability] = {}
    for decl in capability_decls():
        runner = runners.get(decl.id)
        if runner is None:
            raise RuntimeError(
                f"capability {decl.id!r} is declared but this build carries no body for it; "
                f"the registry serves {', '.join(sorted(runners))}"
            )
        served[decl.id] = Capability(decl=decl, run=runner)
    return MappingProxyType(served)


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

    A reuse is the one case where the two differ, by one member and no other.
    ``reused`` states what **this invocation** did, and the job it re-reports
    did the work, so the document on disk keeps ``false`` -- it would otherwise
    have to be rewritten, which would break the seal that hashes it.

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
            return EXIT_SIGINT, _dismissed_text(job)
    if outcome.reused:
        return outcome.exit_code, reused_outcome_text(job)
    return outcome.exit_code, _outcome_text(job)


def _outcome_text(job: JobDirectory) -> str:
    """The exact bytes of ``outcome.json``, or nothing when it is absent."""
    if not job.outcome_path.is_file():
        return ""
    return job.outcome_path.read_text(encoding="utf-8")


def _dismissed_text(job: JobDirectory) -> str:
    """The outcome of a cancelled job, and nothing when the file is another's.

    A capability writes its dismissed outcome as it unwinds, and that document
    is what a cancelled invocation puts on stdout. But a cancellation can also
    land in a branch that writes nothing and must not: resolving a request
    against a directory that is **already sealed**. There the file on disk is
    the finished job's outcome, saying ``successful`` and 0, and printing it
    beside exit 130 would hand a caller a document that contradicts the code it
    was given -- the one thing this verb exists to make impossible.

    So the rule is stated rather than assumed: a process exiting on a signal
    publishes a dismissed document, or none at all.
    """
    text = _outcome_text(job)
    if not text:
        return ""
    try:
        document = json.loads(text)
    except json.JSONDecodeError:
        return ""
    return text if document.get("status") == DISMISSED_STATUS else ""


def declaration_for(capability_id: str) -> CapabilityDecl | None:
    """Return one declaration, or ``None`` for an id this build does not serve.

    The lookup a chain document is resolved against, and deliberately not
    :func:`capability`: a name written in a file is bad input and gets a
    pointer, where a name typed on the command line is a usage error. It reads
    the declarations alone, so refusing a chain imports no engine at all.
    """
    for decl in capability_decls():
        if decl.id == capability_id:
            return decl
    return None


def run_capability_chain(chain_dir: str | Path) -> tuple[int, str]:
    """Run every step of one chain document, and return its code and bytes.

    The composition itself lives in :mod:`hydromodpy.schema.job.chain`, which
    knows no capability: what this function adds is the registry that turns an
    id into a declaration and into a body, which is what nothing below ``cli``
    can see.

    A chain document that does not resolve leaves the root exactly as the
    caller staged it -- no step directory, no report -- because refusing a
    document before it runs is the one case where writing anything would be
    writing about work nobody did. Everything after the first step has started
    ends in the report, including a cancellation.
    """
    from hydromodpy.cli.helpers import exit_code_for
    from hydromodpy.schema.job.chain import CHAIN_FILENAME, read_chain, run_chain

    root = Path(chain_dir).expanduser()
    if not root.is_dir():
        raise JobUsageError(f"chain directory {root} does not exist")
    root = root.resolve()
    chain_path = root / CHAIN_FILENAME
    if not chain_path.is_file():
        raise JobUsageError(f"chain directory {root} carries no {CHAIN_FILENAME}")
    outcome = run_chain(
        read_chain(chain_path),
        root,
        declaration=declaration_for,
        run_step=run_capability,
        exit_code_for=exit_code_for,
    )
    return outcome.exit_code, _chain_outcome_text(root)


def _chain_outcome_text(root: Path) -> str:
    """The exact bytes of the report, read back for the reason ``run`` gives."""
    from hydromodpy.schema.job.chain import CHAIN_OUTCOME_FILENAME

    path = root / CHAIN_OUTCOME_FILENAME
    return path.read_text(encoding="utf-8") if path.is_file() else ""


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
    "declaration_for",
    "describe_capability",
    "list_capabilities",
    "run_capability",
    "run_capability_chain",
    "verify_capability_job",
]
