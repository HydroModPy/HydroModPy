"""The typed outcome of one job: status, exit code, timing, errors.

Also the payload the process prints on stdout, byte for byte, so a caller that
captured the pipe and a caller that reads the directory learn the same thing.

``status`` uses the four OGC API Processes values as a **vocabulary and not a
protocol**, plus ``dismissed`` for a cancelled job. A capability process only
ever writes ``successful``, ``failed`` or ``dismissed``: ``accepted`` and
``running`` describe a job before the process starts, which is the business of
whoever tracks it and not of the process itself. That is why this module's
status type carries three values and refuses the other two by type.

``duration_s`` is computed from the two timestamps every time the document is
rendered, never stored: 78 of 78 real run manifests carry a duration that
contradicts the timestamps next to it, and a number that can disagree with its
own inputs eventually does.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal, get_args

from hydromodpy.core.exceptions import HydroModPyError
from hydromodpy.schema.job.directory import JobDirectory
from hydromodpy.schema.job.documents import write_document

OUTCOME_SCHEMA = "hmp-outcome/v1"

JobStatus = Literal["successful", "failed", "dismissed"]

DISMISSED_STATUS: JobStatus = "dismissed"
"""What a cancelled job writes, and the only status a signal may publish.

A process that exits on a signal exits 130, and the document it puts on stdout
has to agree with that. Spelled once here because three places need it: the
constructor of a dismissed outcome, the runtime that decides what a cancelled
invocation prints, and the generated process description.
"""

UNTYPED_ERROR_CODE = "HMPY.E000"
"""What an exception that is not one of ours is reported as."""

UNIDENTIFIED_JOB = "urn:hmp:job:unidentified"
"""The ``job_id`` of a job whose inputs never resolved.

A job id is the digest of what was asked, so a request that could not be read
or could not be validated has none: there is no resolved input mapping to
address. Spelled as a urn rather than left empty, because an empty string in
a document is read as a missing value and this one is a stated fact -- the
job failed before it could be identified, and no reuse short-circuit may ever
match it."""


def now() -> str:
    """The one spelling of an instant in a job document."""
    return datetime.now(UTC).isoformat()


def error_record(exc: BaseException, *, occurred_at: str | None = None) -> dict[str, Any]:
    """Render *exc* as the problem object a caller outside this process reads.

    A typed failure renders itself, pointers included. Anything else is
    reported under the untyped code rather than dressed up as a typed one: a
    caller reading ``HMPY.E000`` knows it found a bug here, not bad input.
    """
    if isinstance(exc, HydroModPyError):
        payload = exc.to_dict()
    else:
        payload = {
            "type": f"urn:hmp:error:{UNTYPED_ERROR_CODE}",
            "code": UNTYPED_ERROR_CODE,
            "title": type(exc).__name__,
            "detail": str(exc),
        }
    payload["occurred_at"] = occurred_at if occurred_at is not None else now()
    return payload


_RECORD_MEMBERS = frozenset({"id", "path", "mediaType", "bytes", "sha256"})
"""The members :class:`OutputRecord` renders itself. The rest is ``extra``."""


@dataclass(frozen=True, slots=True)
class OutputRecord:
    """One artefact that was produced, hashed from the bytes on disk."""

    id: str
    path: str
    media_type: str
    bytes: int
    sha256: str
    extra: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "extra", MappingProxyType(dict(self.extra)))

    def to_document(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "path": self.path,
            "mediaType": self.media_type,
            "bytes": self.bytes,
            "sha256": self.sha256,
            **dict(self.extra),
        }

    @classmethod
    def from_document(cls, entry: Mapping[str, Any]) -> OutputRecord:
        """Read back one record, every member a capability declared included."""
        return cls(
            id=str(entry["id"]),
            path=str(entry["path"]),
            media_type=str(entry["mediaType"]),
            bytes=int(entry["bytes"]),
            sha256=str(entry["sha256"]),
            extra={key: value for key, value in entry.items() if key not in _RECORD_MEMBERS},
        )


@dataclass(frozen=True, slots=True)
class JobOutcome:
    """What happened, in the one document a caller is guaranteed to find."""

    job_id: str
    process_id: str
    process_version: str
    status: JobStatus
    exit_code: int
    started_at: str
    finished_at: str
    outputs: tuple[OutputRecord, ...] = ()
    warnings: tuple[str, ...] = ()
    errors: tuple[Mapping[str, Any], ...] = ()
    reused: bool = False

    def __post_init__(self) -> None:
        self._refuse_a_status_that_contradicts_itself()
        if self.duration_s < 0:
            raise ValueError(
                f"job {self.job_id} finished at {self.finished_at}, before it started "
                f"at {self.started_at}"
            )
        object.__setattr__(self, "outputs", tuple(self.outputs))
        object.__setattr__(self, "warnings", tuple(self.warnings))
        object.__setattr__(self, "errors", tuple(dict(entry) for entry in self.errors))

    def _refuse_a_status_that_contradicts_itself(self) -> None:
        """Refuse the three combinations no reader could act on.

        A success carrying an error, a failure exiting 0, or a cancellation
        under another code would each make a shim decide the opposite of what
        happened. The runner is the only caller, so this is a bug here.
        """
        if self.status == "successful":
            if self.exit_code != 0:
                raise ValueError(f"job {self.job_id} succeeded and exits {self.exit_code}")
            if self.errors:
                raise ValueError(
                    f"job {self.job_id} succeeded and carries {len(self.errors)} error(s)"
                )
            return
        if self.status == "failed":
            if self.exit_code == 0:
                raise ValueError(f"job {self.job_id} failed and exits 0")
            if not self.errors:
                raise ValueError(f"job {self.job_id} failed and says why nowhere")
            return
        if self.exit_code != 130:
            raise ValueError(f"job {self.job_id} was dismissed and exits {self.exit_code}")

    @property
    def duration_s(self) -> float:
        """Seconds between the two timestamps, to the millisecond."""
        started = self._instant(self.started_at, "started_at")
        finished = self._instant(self.finished_at, "finished_at")
        return round((finished - started).total_seconds(), 3)

    def _instant(self, value: str, member: str) -> datetime:
        """Parse one instant of the document, refusing a local one.

        An instant without an offset is a reading of somebody's wall clock, and
        two of them subtract into a duration that is wrong by the offset — or
        raise, when the other one carries a zone. A job document states UTC.
        """
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(
                f"job {self.job_id} carries {member}={value!r}, not an instant"
            ) from exc
        if parsed.tzinfo is None:
            raise ValueError(f"job {self.job_id} carries {member}={value!r} without a UTC offset")
        return parsed

    def to_document(self) -> dict[str, Any]:
        return {
            "schema": OUTCOME_SCHEMA,
            "job_id": self.job_id,
            "process": {"id": self.process_id, "version": self.process_version},
            "status": self.status,
            "exit_code": self.exit_code,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_s": self.duration_s,
            "reused": self.reused,
            "outputs": [output.to_document() for output in self.outputs],
            "warnings": list(self.warnings),
            "errors": [dict(entry) for entry in self.errors],
        }

    @classmethod
    def from_document(cls, document: Mapping[str, Any]) -> JobOutcome:
        """Read back an outcome this module wrote, and refuse one it did not.

        ``duration_s`` is not read: it is derived from the two instants every
        time the document is rendered, and giving a stored number a second life
        is the defect that made it derived in the first place. ``schema`` is not
        read either -- it names the shape, and the shape is this class.

        The status is checked against the type rather than left to
        :meth:`_refuse_a_status_that_contradicts_itself`, which would read an
        ``accepted`` job exiting 130 as a dismissed one.

        ``reused`` is required and not defaulted, although :meth:`to_document`
        always writes it. A document that omits it was not written by this
        contract, and the reuse path substitutes that member into the bytes on
        disk: defaulting it here would accept a document that the substitution
        would then **append** to rather than change, turning "exactly one member
        differs" into a statement nothing keeps.
        """
        process = document.get("process")
        if not isinstance(process, Mapping):
            raise ValueError("outcome document carries no process block")
        status = document["status"]
        if status not in get_args(JobStatus):
            raise ValueError(f"outcome document carries the status {status!r}")
        return cls(
            job_id=str(document["job_id"]),
            process_id=str(process["id"]),
            process_version=str(process["version"]),
            status=status,
            exit_code=int(document["exit_code"]),
            started_at=str(document["started_at"]),
            finished_at=str(document["finished_at"]),
            outputs=tuple(
                OutputRecord.from_document(entry) for entry in document.get("outputs", ())
            ),
            warnings=tuple(str(entry) for entry in document.get("warnings", ())),
            errors=tuple(dict(entry) for entry in document.get("errors", ())),
            reused=bool(document["reused"]),
        )

    def write(self, job: JobDirectory) -> Path:
        """Write the outcome into *job*, whole or not at all."""
        return write_document(job.outcome_path, self.to_document())


def dismissed(
    *,
    job_id: str,
    process_id: str,
    process_version: str,
    started_at: str,
    exc: BaseException,
    warnings: Sequence[str] = (),
) -> JobOutcome:
    """The outcome of a job a scheduler cancelled.

    No output is claimed, because a cancellation unwinds the stack wherever it
    was, and the seal is never written: a dismissed job directory is readable
    and explicitly unfinished.
    """
    return JobOutcome(
        job_id=job_id,
        process_id=process_id,
        process_version=process_version,
        status=DISMISSED_STATUS,
        exit_code=130,
        started_at=started_at,
        finished_at=now(),
        warnings=tuple(warnings),
        errors=(error_record(exc),),
    )


__all__ = [
    "DISMISSED_STATUS",
    "OUTCOME_SCHEMA",
    "UNIDENTIFIED_JOB",
    "UNTYPED_ERROR_CODE",
    "JobOutcome",
    "JobStatus",
    "OutputRecord",
    "dismissed",
    "error_record",
    "now",
]
