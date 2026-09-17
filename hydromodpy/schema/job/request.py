"""The input document, read and refused in one typed shape.

``request.json`` is the only file the caller writes. It follows the OGC API
Processes execute-request shape verbatim, because that is the one place where
copying a foreign shape costs nothing and saves every shim a translation
layer: ``process``, ``inputs``, ``outputs``, ``response``.

Reading it never touches the filesystem beyond that one file, and every
refusal leaves this module as a ``ConfigValidationError`` pointed at the
member the document wrote. A capability body therefore receives either a
validated model or nothing at all.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from hydromodpy.core.exceptions import CapabilityVersionMismatchError, ConfigValidationError
from hydromodpy.core.toml_io.error_locator import format_validation_error, validation_error_details
from hydromodpy.schema.capability import CAPABILITY_VERSION_PATTERN, CapabilityDecl, OutputDecl
from hydromodpy.schema.job.directory import JobDirectory
from hydromodpy.schema.job.refusal import refuse_request

# The error locator finds line numbers by looking for TOML tokens. A JSON
# request has none, so no text is handed to it: a fault carries no line rather
# than a line that is a guess.
_NO_SOURCE_TEXT = ""


class ProcessRef(BaseModel):
    """Which capability, and at which version, the caller believes it calls."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(description="capability id, as `hmp process list` spells it")
    version: str | None = Field(
        default=None,
        description="advisory capability version, x.y.z; a major mismatch is refused",
    )


class FileLink(BaseModel):
    """A file input: where it is, what it is, and optionally what it hashes to."""

    model_config = ConfigDict(extra="forbid")

    href: str = Field(description="absolute path, or a path relative to the job directory")
    type: str | None = Field(default=None, description="IANA media type of the file")
    sha256: str | None = Field(default=None, description="expected digest, lowercase hex")


class JobRequest(BaseModel):
    """The execute request, as the caller wrote it.

    The one model of this repository that accepts unknown members, and it does
    so at the top level only: an OGC client legitimately sends envelope members
    this process has no use for, and refusing the whole job over one of them
    would be refusing a request whose inputs are all valid. ``inputs`` is
    validated against the capability's own model, which forbids extras.
    """

    model_config = ConfigDict(extra="allow")

    process: ProcessRef
    inputs: dict[str, Any] = Field(default_factory=dict)
    outputs: dict[str, Any] = Field(default_factory=dict)
    response: str = Field(
        default="document",
        description="accepted and ignored; the only transmission is by reference",
    )

    @property
    def undeclared_members(self) -> tuple[str, ...]:
        """Envelope members this process ignores, for the caller's warning."""
        return tuple(sorted(self.model_extra or {}))


def read_request(job: JobDirectory) -> JobRequest:
    """Read and validate ``request.json`` from *job*."""
    source = str(job.request_path)
    text = job.request_path.read_text(encoding="utf-8")
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
            msg="the request document must be a JSON object",
            source=source,
        )
    try:
        return JobRequest.model_validate(dict(payload))
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


def check_process(request: JobRequest, decl: CapabilityDecl) -> tuple[str, ...]:
    """Check which capability the request targets, and return its warnings.

    The version is advisory, as the description says: a different patch or
    minor is a warning the caller reads on stderr, because refusing it would
    make every shim pin a build. A different **major** is refused, because
    that is the version a caller pins precisely so it is told when the
    contract it read no longer holds.
    """
    if request.process.id != decl.id:
        raise refuse_request(
            f"request targets capability {request.process.id!r}, which is not {decl.id!r}",
            loc=("process", "id"),
            msg=f"expected {decl.id!r}",
        )
    version = request.process.version
    if version is None:
        return ()
    if not CAPABILITY_VERSION_PATTERN.match(version):
        raise refuse_request(
            f"request version {version!r} is not a three-part version",
            loc=("process", "version"),
            msg="expected a version of the form x.y.z",
        )
    if int(version.split(".")[0]) != decl.major:
        raise CapabilityVersionMismatchError(
            f"request targets {decl.id}@{version}, and this build carries {decl.version}; "
            "a major version is the contract a caller pins",
        )
    if version == decl.version:
        return ()
    return (f"request targets {decl.id} {version}; this build carries {decl.version}",)


def requested_outputs(request: JobRequest, decl: CapabilityDecl) -> tuple[OutputDecl, ...]:
    """Resolve which declared outputs the caller asked to hear about.

    An empty or absent ``outputs`` member means all of them. Naming one the
    capability does not declare is refused, pointed at the name: a caller that
    expects an artefact nobody produces must learn it before the run, not by
    finding the file missing after the seal.
    """
    wanted = dict(request.outputs)
    if not wanted:
        return decl.outputs
    declared = set(decl.output_ids)
    unknown = sorted(name for name in wanted if name not in declared)
    if unknown:
        raise refuse_request(
            f"capability {decl.id!r} declares no output named {unknown[0]!r}; "
            f"it declares {', '.join(decl.output_ids)}",
            loc=("outputs", unknown[0]),
            msg=f"unknown output {unknown[0]!r}",
        )
    return tuple(output for output in decl.outputs if output.id in wanted)


def validate_inputs(request: JobRequest, decl: CapabilityDecl) -> BaseModel:
    """Validate ``inputs`` against the capability's own request model."""
    document: dict[str, Any] = {"inputs": dict(request.inputs)}
    try:
        return decl.request_model.model_validate(dict(request.inputs))
    except ValidationError as exc:
        raise ConfigValidationError(
            format_validation_error(
                exc,
                text=_NO_SOURCE_TEXT,
                loc_prefix=("inputs",),
                document=document,
            ),
            details=validation_error_details(
                exc,
                text=_NO_SOURCE_TEXT,
                loc_prefix=("inputs",),
                document=document,
            ),
        ) from exc


__all__ = [
    "FileLink",
    "JobRequest",
    "ProcessRef",
    "check_process",
    "read_request",
    "requested_outputs",
    "validate_inputs",
]
