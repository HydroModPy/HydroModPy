"""Running several capabilities in a row, each one feeding the next by file.

A capability is a function from a validated document to a directory of sealed
artefacts, and two of them compose through the disk: the GeoPackage
``terrain-delineate`` seals is a mask ``data-fetch`` reads. Nothing in this
repository performed that composition -- the caller had to create both
directories, write both ``request.json`` by hand, and know which artefact of
the first fills which member of the second.

This module is that missing component, and it knows no capability. It reads a
chain document, resolves each link against the **declaration** of the step it
comes from, writes each ``request.json``, and hands the directory to a runner
it was given. Which capabilities exist and how one is executed are injected,
because the registry that pairs a declaration with a body lives in ``cli`` and
nothing below it can see both.

Five rules it keeps, each one a defect it exists to make impossible.

**A link is resolved before the first step runs.** A chain whose second step
names an artefact its capability does not declare is refused while the root is
still empty, not after ten minutes of flow routing. That is why resolution is
a pass of its own and takes the declarations rather than the bodies.

**The written link is absolute.** :meth:`JobDirectory.resolve_input` resolves a
relative input against the job directory and refuses one that walks out of it,
which is exactly what a sibling step directory is. A chain that wrote
``../01-delineate/outputs/watershed.gpkg`` would produce a document every step
refuses.

**A step directory is a job directory and carries nothing else.** The chain
writes its own report at the chain root, never inside a step:
``ALLOWED_JOB_ENTRIES`` lists every name a job directory may hold, and a chain
bookkeeping file is not one of them.

**Every path produces one report.** A step that fails, a link whose file is
missing, a cancellation between two steps: each finishes the document, so a
caller that captured stdout and a caller that opens the root learn the same
thing. The one way to have work done and nothing to report it in -- a root
whose report name is already taken by a directory -- is refused before the
first step runs.

**The exit code of a step decides, and its document never overrules it.** The
status in the report is read off the code, because the code is what stops the
chain and what the chain exits with. A runner whose document says something
else is publishing a contradiction, and the step record carries it as a fault
rather than passing it on -- a report saying ``failed`` beside ``exit_code: 0``
is the one document nobody can act on.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from hydromodpy.core.exceptions import ConfigValidationError, JobUsageError
from hydromodpy.core.toml_io.error_locator import format_validation_error, validation_error_details
from hydromodpy.schema.capability import CapabilityDecl
from hydromodpy.schema.job.documents import write_document
from hydromodpy.schema.job.layout import REQUEST_FILENAME
from hydromodpy.schema.job.outcome import JobStatus, error_record, now
from hydromodpy.schema.job.refusal import refuse_request
from hydromodpy.schema.job.request import JobRequest, ProcessRef, check_process

CHAIN_FILENAME = "chain.json"
"""The document the caller writes at the chain root, and the only one."""

CHAIN_OUTCOME_FILENAME = "chain-outcome.json"
"""What the chain leaves beside it: one record per declared step."""

CHAIN_OUTCOME_SCHEMA = "hmp-chain-outcome/v1"

STEP_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_-]*$"
"""The spelling a step id may take, because it names a directory.

The same pattern an outlet id takes, and for the same reason: the refusal
happens at the boundary, pointed at the member of the document that carries
it, instead of at a filesystem error three calls down.
"""

MAX_STEPS = 32
"""Declared so a chain document has a stated bound like every other input."""

NOT_RUN: Literal["skipped"] = "skipped"
"""The status of a step the chain never submitted, because an earlier one failed.

A fourth value beside the three of :data:`~hydromodpy.schema.job.outcome.JobStatus`,
and not one of them: the step has no outcome, no job id and no directory
content, so calling it failed would publish a failure nobody produced.
"""

ChainStepStatus = JobStatus | Literal["skipped"]

# The error locator finds line numbers by looking for TOML tokens. A JSON
# document has none, so no text is handed to it.
_NO_SOURCE_TEXT = ""


class StepLink(BaseModel):
    """One member of a step's inputs, filled from an earlier step's artefact."""

    model_config = ConfigDict(extra="forbid")

    member: str = Field(
        min_length=1,
        description="member of this step's inputs to fill with the artefact",
    )
    step: str = Field(
        min_length=1,
        description="id of an earlier step of this chain",
    )
    output: str = Field(
        min_length=1,
        description="artefact of that step, as its capability declares it",
    )


class ChainStep(BaseModel):
    """One capability invocation, and where its file inputs come from."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(
        min_length=1,
        max_length=64,
        pattern=STEP_ID_PATTERN,
        description="identifier of the step, usable as a directory name",
        examples=["delineate"],
    )
    process: ProcessRef = Field(
        description="which capability this step runs, and at which version",
    )
    inputs: dict[str, Any] = Field(
        default_factory=dict,
        description="the inputs member of this step's request, minus what links fill",
    )
    links: list[StepLink] = Field(
        default_factory=list,
        description="file inputs taken from an artefact of an earlier step",
    )


class ChainRequest(BaseModel):
    """The document a chain root carries: steps, in the order they run."""

    model_config = ConfigDict(extra="forbid")

    steps: list[ChainStep] = Field(
        min_length=1,
        max_length=MAX_STEPS,
        description="capability invocations, run in order until one fails",
    )

    @model_validator(mode="after")
    def _refuse_a_chain_that_cannot_be_ordered(self) -> ChainRequest:
        """Refuse every link that no sequential execution could satisfy.

        Checked here rather than at resolution because none of it needs a
        declaration: an id repeated, a link pointing forward and two links
        fighting over one member are faults of the document alone, and the
        caller learns all of them without this build knowing a capability.
        """
        seen: dict[str, int] = {}
        for position, step in enumerate(self.steps):
            # Case-folded: a step id names a directory, and a case-insensitive
            # filesystem makes ``Fetch`` and ``fetch`` one directory.
            folded = step.id.casefold()
            if folded in seen:
                raise ValueError(
                    f"steps repeat the id {step.id!r}, case-folded; each one names a directory"
                )
            self._refuse_unusable_links(step, earlier=set(seen))
            seen[folded] = position
        return self

    @staticmethod
    def _refuse_unusable_links(step: ChainStep, *, earlier: set[str]) -> None:
        """Refuse the three link faults a single step can carry."""
        filled: set[str] = set()
        for link in step.links:
            if link.step.casefold() not in earlier:
                raise ValueError(
                    f"step {step.id!r} links {link.member!r} to step {link.step!r}, which does "
                    "not run before it; a chain runs its steps in the order they are written"
                )
            if link.member in step.inputs:
                raise ValueError(
                    f"step {step.id!r} writes {link.member!r} in its inputs and links it as "
                    "well; a member is given once, literally or by link"
                )
            if link.member in filled:
                raise ValueError(
                    f"step {step.id!r} links {link.member!r} twice; the second would silently "
                    "replace the first"
                )
            filled.add(link.member)


@dataclass(frozen=True, slots=True)
class ResolvedLink:
    """One link, with the artefact it names located under the chain root."""

    member: str
    step_id: str
    output_id: str
    path: str
    """Where the artefact lands, relative to the chain root, forward slashes."""

    media_type: str

    def to_document(self) -> dict[str, Any]:
        return {
            "member": self.member,
            "step": self.step_id,
            "output": self.output_id,
            "path": self.path,
            "type": self.media_type,
        }


@dataclass(frozen=True, slots=True)
class ResolvedStep:
    """One step, its declaration, the directory it gets and its located links."""

    position: int
    step: ChainStep
    decl: CapabilityDecl
    directory: str
    links: tuple[ResolvedLink, ...]


def read_chain(path: str | Path) -> ChainRequest:
    """Read and validate the chain document at *path*.

    Refused the way ``request.json`` is refused, in the one shape the config
    boundary already speaks: a :class:`ConfigValidationError` carrying one
    record per fault with the pointer of the member the document wrote.
    """
    source = str(path)
    # utf-8-sig for the same reason ``read_request`` gives: a document written
    # from .NET or PowerShell carries a byte-order mark, and every JSON reader
    # in the world accepts it.
    text = Path(path).read_text(encoding="utf-8-sig")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ConfigValidationError(
            f"{source} is not valid JSON: {exc.msg} at line {exc.lineno} column {exc.colno}",
            source=source,
        ) from exc
    if not isinstance(payload, Mapping):
        raise refuse_request(
            f"{source} holds a JSON {type(payload).__name__}, not an object",
            loc=(),
            msg="the chain document must be a JSON object",
            source=source,
        )
    try:
        return ChainRequest.model_validate(dict(payload))
    except ValidationError as exc:
        raise ConfigValidationError(
            format_validation_error(
                exc, source_path=source, text=_NO_SOURCE_TEXT, document=payload
            ),
            details=validation_error_details(
                exc, source_path=source, text=_NO_SOURCE_TEXT, document=payload
            ),
            source=source,
        ) from exc


def step_directory(position: int, step_id: str) -> str:
    """Name the directory of the step at *position*, zero-based.

    Prefixed by its rank because the order is the whole contract of a chain,
    and a reader listing the root learns it without opening a document.
    """
    return f"{position + 1:02d}-{step_id}"


def resolve_chain(
    chain: ChainRequest,
    *,
    declaration: Callable[[str], CapabilityDecl | None],
) -> tuple[ResolvedStep, ...]:
    """Locate every step and every link, before a single directory is created.

    *declaration* answers ``None`` for an id this build does not serve, which
    is refused here as a member of the document rather than raised as a usage
    error: the name came from a file the caller wrote, so it is bad input and
    it has a pointer.
    """
    produced: dict[str, ResolvedStep] = {}
    resolved: list[ResolvedStep] = []
    for position, step in enumerate(chain.steps):
        decl = declaration(step.process.id)
        if decl is None:
            raise refuse_request(
                f"step {step.id!r} runs capability {step.process.id!r}, which this build "
                "does not serve",
                loc=("steps", str(position), "process", "id"),
                msg=f"unknown capability {step.process.id!r}",
            )
        # Called for what it refuses, not for what it returns: a major version
        # this build does not carry stops the chain before the first step runs.
        # Its warnings are dropped here on purpose -- the step states its own in
        # its outcome, and repeating them would report the same fact twice, once
        # for a step that may never run.
        check_process(JobRequest(process=step.process, inputs=dict(step.inputs)), decl)
        entry = ResolvedStep(
            position=position,
            step=step,
            decl=decl,
            directory=step_directory(position, step.id),
            links=_resolve_links(step, position, produced),
        )
        produced[step.id.casefold()] = entry
        resolved.append(entry)
    return tuple(resolved)


def _resolve_links(
    step: ChainStep,
    position: int,
    produced: Mapping[str, ResolvedStep],
) -> tuple[ResolvedLink, ...]:
    """Turn each link of *step* into a path under the chain root.

    *produced* holds the steps that run before this one, which the document
    validator has already made a precondition: a link pointing forward or at
    itself never reaches here.
    """
    links: list[ResolvedLink] = []
    for index, link in enumerate(step.links):
        producer = produced[link.step.casefold()]
        try:
            output = producer.decl.output(link.output)
        except KeyError:
            raise refuse_request(
                f"step {step.id!r} links {link.member!r} to output {link.output!r} of step "
                f"{link.step!r}, and {producer.decl.id} declares "
                f"{', '.join(producer.decl.output_ids)}",
                loc=("steps", str(position), "links", str(index), "output"),
                msg=f"unknown output {link.output!r}",
            ) from None
        links.append(
            ResolvedLink(
                member=link.member,
                step_id=link.step,
                output_id=link.output,
                path=f"{producer.directory}/{output.path}",
                media_type=output.media_type,
            )
        )
    return tuple(links)


def write_step_request(root: Path, resolved: ResolvedStep) -> Path:
    """Write the ``request.json`` of one step, links resolved to absolute paths.

    Absolute, and this is the one place the reason matters: a step directory
    resolves a relative input against itself and refuses one that escapes, so
    a sibling directory can only be named in full. The chain root is resolved
    once by the caller, which is what makes these paths stable whatever the
    working directory of the process is.
    """
    directory = root / resolved.directory
    directory.mkdir(parents=True, exist_ok=True)
    inputs: dict[str, Any] = dict(resolved.step.inputs)
    for link in resolved.links:
        inputs[link.member] = {
            "href": str(root / link.path),
            "type": link.media_type,
        }
    document: dict[str, Any] = {
        "process": {"id": resolved.step.process.id},
        "inputs": inputs,
    }
    if resolved.step.process.version is not None:
        document["process"]["version"] = resolved.step.process.version
    return write_document(directory / REQUEST_FILENAME, document)


@dataclass(frozen=True, slots=True)
class ChainOutcome:
    """What the chain did, as the document it writes and puts on stdout."""

    exit_code: int
    document: dict[str, Any]


def run_chain(
    chain: ChainRequest,
    root: str | Path,
    *,
    declaration: Callable[[str], CapabilityDecl | None],
    run_step: Callable[[str, Path], tuple[int, str]],
    exit_code_for: Callable[[BaseException], int],
) -> ChainOutcome:
    """Run every step of *chain* under *root*, stopping at the first failure.

    *run_step* receives a capability id and a directory that already carries
    its request, and answers the pair ``hmp process run`` answers with: the
    typed exit code, and the bytes of the job's ``outcome.json``. Injected
    because the registry that can produce a body lives above this layer.

    A step that fails stops the chain: the steps after it are recorded as
    ``skipped``, which is a statement that they did not run and not a failure
    attributed to them. Cancellation is treated the same way, because a chain
    has nothing of its own to unwind -- the step that was running wrote its
    own dismissed outcome before this function saw the code.
    """
    started_at = now()
    # Resolved here and not by the caller: every link this function writes is
    # an absolute path built from it, and a relative root would produce a
    # relative href, which a job directory resolves against *itself*. The
    # guarantee has to be a property of this function.
    root = Path(root).resolve()
    _refuse_a_root_that_cannot_be_reported_into(root)
    resolved = resolve_chain(chain, declaration=declaration)
    records: list[dict[str, Any]] = []
    exit_code = 0
    for index, entry in enumerate(resolved):
        record = _pending_record(entry)
        records.append(record)
        try:
            # Before the directory exists, so a step whose input was never
            # produced leaves no half-staged job behind.
            _refuse_a_link_that_was_never_produced(root, entry)
            write_step_request(root, entry)
            step_exit, payload = run_step(entry.decl.id, root / entry.directory)
        except KeyboardInterrupt as exc:
            _close_record(record, status="dismissed", exit_code=130, errors=(error_record(exc),))
            exit_code = 130
            _skip_the_rest(records, resolved, index + 1)
            break
        except Exception as exc:  # noqa: BLE001 - every failure becomes a typed record
            step_code = exit_code_for(exc)
            _close_record(record, status="failed", exit_code=step_code, errors=(error_record(exc),))
            exit_code = step_code
            _skip_the_rest(records, resolved, index + 1)
            break
        _read_back_outcome(record, payload, step_exit)
        if step_exit != 0:
            exit_code = step_exit
            _skip_the_rest(records, resolved, index + 1)
            break
    document = {
        "schema": CHAIN_OUTCOME_SCHEMA,
        "status": _chain_status(records),
        "exit_code": exit_code,
        "started_at": started_at,
        "finished_at": now(),
        "steps": records,
    }
    write_document(root / CHAIN_OUTCOME_FILENAME, document)
    return ChainOutcome(exit_code=exit_code, document=document)


def _refuse_a_root_that_cannot_be_reported_into(root: Path) -> None:
    """Refuse a root whose report name is already taken by something else.

    Checked before the first step and not at the end, which is where the write
    happens: a chain that ran two capabilities and then could not write its
    report has done the work and says so nowhere, and the caller reading stdout
    gets nothing at all. A directory sitting where the report goes is the one
    shape of that failure a caller can be told about in advance, so it is.
    """
    report = root / CHAIN_OUTCOME_FILENAME
    if report.exists() and not report.is_file():
        raise JobUsageError(
            f"chain directory {root} already carries a {CHAIN_OUTCOME_FILENAME} that is not "
            "a file, and the report of this run has nowhere to go"
        )


def _pending_record(entry: ResolvedStep) -> dict[str, Any]:
    """The record of a step about to run, in the order a reader wants it."""
    return {
        "id": entry.step.id,
        "dir": entry.directory,
        "process": {"id": entry.decl.id, "version": entry.decl.version},
        "status": NOT_RUN,
        "exit_code": None,
        "job_id": None,
        "reused": False,
        "inputs_from": [link.to_document() for link in entry.links],
    }


def _close_record(
    record: dict[str, Any],
    *,
    status: ChainStepStatus,
    exit_code: int,
    errors: Sequence[Mapping[str, Any]] = (),
) -> None:
    record["status"] = status
    record["exit_code"] = exit_code
    if errors:
        record["errors"] = [dict(error) for error in errors]


def _read_back_outcome(record: dict[str, Any], payload: str, step_exit: int) -> None:
    """Fill a step record from the outcome document the run put on stdout.

    Read from the payload rather than from the disk: it is the same bytes for
    every path but one, and on that path -- a reuse -- it is the payload that
    states what *this* invocation did.
    """
    record["exit_code"] = step_exit
    try:
        outcome = json.loads(payload) if payload else {}
    except json.JSONDecodeError:
        outcome = {}
    if not isinstance(outcome, Mapping):
        outcome = {}
    record["status"] = _status_of(step_exit)
    record["job_id"] = outcome.get("job_id")
    record["reused"] = bool(outcome.get("reused", False))
    for member in ("warnings", "errors"):
        stated = outcome.get(member) or ()
        if stated:
            record[member] = list(stated)
    _report_a_document_that_contradicts_its_code(record, outcome, step_exit)


def _report_a_document_that_contradicts_its_code(
    record: dict[str, Any], outcome: Mapping[str, Any], step_exit: int
) -> None:
    """Publish a runner whose document and whose exit code say different things.

    The status of a step is read off its **exit code** and never off the
    document it printed, because the code is what the chain acts on: it is what
    stops the chain and what the chain exits with. Copying a status that
    disagreed with it produced the one document nobody can act on -- a report
    saying ``failed`` beside ``"exit_code": 0`` -- which is exactly what
    :meth:`JobOutcome._refuse_a_status_that_contradicts_itself` refuses one
    layer down.

    Not silently dropped either: a disagreement is a defect of whoever ran the
    step, and the step record carries it as a fault rather than hiding it
    behind the code that won.
    """
    stated = outcome.get("status")
    if stated is None or stated == record["status"]:
        return
    record.setdefault("errors", []).append(
        error_record(
            ValueError(
                f"the step printed a document saying {stated!r} and exited {step_exit}, "
                f"which this build reads as {record['status']!r}; the exit code decides"
            )
        )
    )


def _status_of(exit_code: int) -> ChainStepStatus:
    """What a step that published no document did, read off its exit code.

    A cancelled job whose directory was already sealed prints nothing at all --
    the runtime refuses to hand back a finished job's outcome beside exit 130 --
    so the code is the only statement left, and 130 says dismissed and not
    failed.
    """
    if exit_code == 0:
        return "successful"
    return "dismissed" if exit_code == 130 else "failed"


def _skip_the_rest(
    records: list[dict[str, Any]], resolved: Sequence[ResolvedStep], start: int
) -> None:
    """Account for every declared step, including the ones never submitted."""
    records.extend(_pending_record(entry) for entry in resolved[start:])


def _chain_status(records: Sequence[Mapping[str, Any]]) -> str:
    """The status of the chain: that of the step that stopped it."""
    for record in records:
        if record["status"] in ("failed", "dismissed"):
            return str(record["status"])
    if any(record["status"] == NOT_RUN for record in records):
        return "failed"
    return "successful"


def _refuse_a_link_that_was_never_produced(root: Path, entry: ResolvedStep) -> None:
    """Refuse a link whose file the producing step did not write.

    Half the artefacts of this tree are declared ``required=False`` -- a
    ``data-fetch`` run writes one payload of four -- so a link can name a
    declared output that this particular run legitimately did not produce. The
    step that would read it is refused before it starts, pointed at the link,
    rather than started and failed on a missing file whose name says nothing
    about which member of which document was wrong.
    """
    for index, link in enumerate(entry.links):
        if (root / link.path).exists():
            continue
        raise refuse_request(
            f"step {entry.step.id!r} reads {link.member!r} from {link.path}, which step "
            f"{link.step_id!r} did not produce; {link.output_id!r} is a declared artefact "
            "its run did not write",
            loc=("steps", str(entry.position), "links", str(index)),
            msg=f"missing artefact {link.output_id!r}",
        )


__all__ = [
    "CHAIN_FILENAME",
    "CHAIN_OUTCOME_FILENAME",
    "CHAIN_OUTCOME_SCHEMA",
    "MAX_STEPS",
    "NOT_RUN",
    "STEP_ID_PATTERN",
    "ChainOutcome",
    "ChainRequest",
    "ChainStep",
    "ChainStepStatus",
    "ResolvedLink",
    "ResolvedStep",
    "StepLink",
    "read_chain",
    "resolve_chain",
    "run_chain",
    "step_directory",
    "write_step_request",
]
