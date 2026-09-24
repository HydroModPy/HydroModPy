"""``data-request``, executed: one job directory in, one seal out.

The request is a :class:`~hydromodpy.data.request.model.DataRequest`, the same
document ``hmp data get`` reads, carried under ``inputs``. The job serves it
with :func:`~hydromodpy.data.request.engine.run_request` and seals what it
wrote under ``outputs/``: one file per variable and source, and the report
``outputs/request.json``.

Four things the job does that ``hmp data get`` does not.

**It touches no workspace and no user cache.** The managers read and fill a
cache under a scratch directory in ``$TMPDIR``, indexed in memory, and both
are gone when the job ends.

**It refuses a** ``custom`` **source.** A job has no user files to read; the
refusal points at the member that names it, before anything is written.

**The extent is resolved before anything is written.** A mask is resolved
against the job directory, hashed, checked against the digest the request
pins, and read, so a request naming a file that is not a vector is refused
with the directory as the caller staged it. The ``job_id`` addresses the mask
by its digest, not by its path.

**A variable that fails fails the job.** Its files are listed in the report
and in no seal: ``manifest.json`` exists only when every asked-for variable was
served, and the exit code is the typed code of the first failure.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, cast

from hydromodpy.core.exceptions import (
    CapabilityVersionMismatchError,
    ConfigValidationError,
    DataCapabilityError,
    DataContractViolation,
    DataProductError,
    DataRequestError,
    DataSourceError,
    JobUsageError,
)
from hydromodpy.data.request.model import DataRequest
from hydromodpy.schema.capability import CapabilityDecl, OutputDecl
from hydromodpy.schema.job.digest import sha256_file
from hydromodpy.schema.job.directory import JobDirectory
from hydromodpy.schema.job.documents import write_document
from hydromodpy.schema.job.extent import SpatialExtent
from hydromodpy.schema.job.inputset import (
    InputResource,
    InputSet,
    build_inputset,
    inline_resource,
)
from hydromodpy.schema.job.outcome import (
    UNIDENTIFIED_JOB,
    JobOutcome,
    OutputRecord,
    dismissed,
    error_record,
    now,
)
from hydromodpy.schema.job.provenance import build_provenance, write_provenance
from hydromodpy.schema.job.refusal import refuse_request
from hydromodpy.schema.job.request import (
    FileLink,
    check_process,
    content_address,
    read_request,
    requested_outputs,
    validate_inputs,
)
from hydromodpy.schema.job.reuse import reuse_sealed_outcome
from hydromodpy.schema.job.seal import seal_job
from hydromodpy.schema.media_types import (
    GEOPACKAGE_MEDIA_TYPE,
    GEOTIFF_MEDIA_TYPE,
    JSON_MEDIA_TYPE,
    NETCDF_MEDIA_TYPE,
    PARQUET_MEDIA_TYPE,
)
from hydromodpy.schema.sources import SOURCES

ExitCodeMapper = Callable[[BaseException], int]
"""How the runtime turns an exception into the status a shim reads."""

CAPABILITY_ID = "data-request"
CAPABILITY_VERSION = "1.0.0"
REPORT_PATH = "outputs/request.json"
CUSTOM_SOURCE = "custom"

MEDIA_TYPES: dict[str, str] = {
    ".parquet": PARQUET_MEDIA_TYPE,
    ".nc": NETCDF_MEDIA_TYPE,
    ".tif": GEOTIFF_MEDIA_TYPE,
    ".gpkg": GEOPACKAGE_MEDIA_TYPE,
}
"""The media type of each file the engine writes, by its suffix."""

REACHED_HOSTS: tuple[str, ...] = tuple(
    sorted({host for entry in SOURCES.values() for host in entry.hosts})
)
"""Every host a source served here contacts, which is what the capability declares.

The union of ``schema/sources.py`` and not the hosts of the sources a given
request names: an orchestrator allows egress before it reads the request. A
plugin source asked under ``installed`` may reach a host outside it; the
report names the sources a run asked.
"""

DATA_REQUEST = CapabilityDecl(
    id=CAPABILITY_ID,
    version=CAPABILITY_VERSION,
    title="Serve [data] sections over an extent and a period, one file per variable",
    description=(
        "Loads each [data] section of the request through its manager over a "
        "bounding box, a vector mask or a list of stations, cuts what comes back "
        "to that extent and period, and seals one file per variable and source "
        "beside a report that lists each file with its checksum."
    ),
    keywords=("data", "fetch", "download", "hydrology", "France"),
    request_model=DataRequest,
    outputs=(
        OutputDecl(
            id="report",
            title="Every file served, its checksum, extent and period, and every failure",
            path=REPORT_PATH,
            media_type=JSON_MEDIA_TYPE,
            roles=("metadata", "primary"),
        ),
        OutputDecl(
            id="inputset",
            title="Resolved, hashed, licence-annotated input set",
            path="inputset.json",
            media_type=JSON_MEDIA_TYPE,
            roles=("metadata", "provenance"),
        ),
        OutputDecl(
            id="outcome",
            title="Typed job outcome",
            path="outcome.json",
            media_type=JSON_MEDIA_TYPE,
            roles=("metadata",),
        ),
    ),
    exceptions=(
        JobUsageError,
        CapabilityVersionMismatchError,
        ConfigValidationError,
        FileNotFoundError,
        DataContractViolation,
        DataRequestError,
        DataCapabilityError,
        DataSourceError,
        DataProductError,
    ),
    env=("HMP_NO_PROGRESS", "HMP_LOG_LEVEL", "TMPDIR"),
    # The managers download into a cache, and a job keeps nothing but its
    # artefacts: that cache, and the polygon a box is written as, live in a
    # scratch directory under $TMPDIR that the job removes.
    writes_outside_jobdir=("$TMPDIR",),
    reaches_network=REACHED_HOSTS,
)
"""The capability that reaches the providers, and says which ones it may reach."""


@dataclass(frozen=True, slots=True)
class _Resolved:
    """What the request resolved to, before anything is written."""

    request: DataRequest
    mask_resource: InputResource | None
    effective_inputs: dict[str, Any]
    job_id: str
    warnings: tuple[str, ...]


def run(job: JobDirectory, *, exit_code_for: ExitCodeMapper) -> JobOutcome:
    """Execute ``data-request`` inside *job* and return what happened.

    Writes ``outcome.json`` in every case, and ``manifest.json`` only when the
    job succeeded.
    """
    if job.is_sealed:
        return _reuse_or_refuse(job)
    started_at = now()
    decl = DATA_REQUEST
    job_id = UNIDENTIFIED_JOB
    try:
        resolved = _resolve(job)
        job_id = resolved.job_id
        return _execute(job, resolved, started_at=started_at, exit_code_for=exit_code_for)
    except KeyboardInterrupt as exc:
        outcome = dismissed(
            job_id=job_id,
            process_id=decl.id,
            process_version=decl.version,
            started_at=started_at,
            exc=exc,
        )
        outcome.write(job)
        raise
    except Exception as exc:
        outcome = JobOutcome(
            job_id=job_id,
            process_id=decl.id,
            process_version=decl.version,
            status="failed",
            exit_code=exit_code_for(exc),
            started_at=started_at,
            finished_at=now(),
            errors=(error_record(exc),),
        )
        outcome.write(job)
        return outcome


def _reuse_or_refuse(job: JobDirectory) -> JobOutcome:
    """Answer a directory that is already sealed, without writing into it."""
    try:
        resolved = _resolve(job)
    except Exception as exc:
        raise JobUsageError(
            f"job directory {job.root} is already sealed, and this request does not "
            f"resolve into a job id to compare against it: {exc}"
        ) from exc
    return reuse_sealed_outcome(job, job_id=resolved.job_id)


def _resolve(job: JobDirectory) -> _Resolved:
    """Read and check the request, and address the work it asks for.

    Everything here happens before a byte is written into the job, so a
    refusal leaves the directory exactly as the caller staged it.
    """
    decl = DATA_REQUEST
    document = read_request(job)
    warnings = list(check_process(document, decl))
    warnings.extend(
        f"request carries the envelope member {member!r}, which this process ignores"
        for member in document.undeclared_members
    )
    request = cast(DataRequest, validate_inputs(document, decl))
    requested_outputs(document, decl)
    _refuse_custom_sources(request)

    mask_resource = None
    if request.extent.mask is not None:
        request, mask_resource = _resolve_mask(job, request)

    effective = request.model_dump(mode="json")
    if mask_resource is not None:
        effective["extent"]["mask"] = {"sha256": mask_resource.sha256}
    return _Resolved(
        request=request,
        mask_resource=mask_resource,
        effective_inputs=effective,
        job_id=content_address(
            process_id=decl.id,
            process_version=decl.version,
            inputs=effective,
        ),
        warnings=tuple(warnings),
    )


def _refuse_custom_sources(request: DataRequest) -> None:
    for variable, section in request.sections().items():
        for index, src in enumerate(getattr(section, "sources", ())):
            if src.source == CUSTOM_SOURCE:
                raise refuse_request(
                    f"[data.{variable}] names a custom source; a job has no user files "
                    "to read, so it serves only the sources that download",
                    loc=("inputs", "data", variable, "sources", str(index), "source"),
                    msg="custom source in a job",
                )


def _resolve_mask(job: JobDirectory, request: DataRequest) -> tuple[DataRequest, InputResource]:
    """Resolve the mask against the job, hash it, check its pin, and read its extent."""
    from hydromodpy.data.common.source_extent import mask_extent

    link = cast(FileLink, request.extent.mask)
    path = job.resolve_input(link.href, loc=("inputs", "extent", "mask", "href"))
    if not path.is_file():
        raise FileNotFoundError(f"input mask names {link.href!r}, and {path} is not a file")
    digest, size = sha256_file(path)
    if link.sha256 is not None and link.sha256.lower() != digest:
        raise DataContractViolation(
            f"input mask {link.href!r} hashes to {digest} and the request pinned "
            f"{link.sha256.lower()}; the bytes are not the ones the job asked for"
        )
    try:
        extent = mask_extent(path)
    except Exception as exc:
        raise DataRequestError(
            f"input mask {link.href!r} cannot be read as a vector with a CRS: {exc}"
        ) from exc
    resource = InputResource(
        name="mask",
        role="extent",
        href=link.href,
        media_type=link.type,
        bytes=size,
        sha256=digest,
        spatial=SpatialExtent(bbox=extent.bbox, crs=extent.crs),
    )
    resolved_link = link.model_copy(update={"href": str(path)})
    extent_in = request.extent.model_copy(update={"mask": resolved_link})
    return request.model_copy(update={"extent": extent_in}), resource


def _execute(
    job: JobDirectory,
    resolved: _Resolved,
    *,
    started_at: str,
    exit_code_for: ExitCodeMapper,
) -> JobOutcome:
    """Serve the request into ``outputs/`` and seal it when every variable was served."""
    from hydromodpy.data.loading.store import DataStore
    from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB
    from hydromodpy.data.request.engine import run_request

    decl = DATA_REQUEST
    job.ensure_workspace()
    with (
        TemporaryDirectory(prefix="hmp-data-request-cache-") as scratch,
        DataCatalogDuckDB() as index,
    ):
        store = DataStore(data_root=Path(scratch) / "data", catalog=index)
        report = run_request(resolved.request, job.outputs_dir, store=store, refuse_custom=True)

    warnings = list(resolved.warnings)
    warnings.extend(
        f"{item.variable} from {item.source} answered with nothing inside the extent and period"
        for item in report.files
        if item.empty
    )
    if report.failures:
        first = report.failures[0].exception or DataRequestError(report.failures[0].error)
        outcome = JobOutcome(
            job_id=resolved.job_id,
            process_id=decl.id,
            process_version=decl.version,
            status="failed",
            exit_code=exit_code_for(first),
            started_at=started_at,
            finished_at=now(),
            outputs=_output_records(job, report),
            warnings=tuple(warnings),
            errors=tuple(
                error_record(failure.exception or DataRequestError(failure.error))
                for failure in report.failures
            ),
        )
        outcome.write(job)
        return outcome

    inputset = _build_inputset(resolved)
    write_document(job.inputset_path, inputset.to_document())
    write_provenance(
        job,
        build_provenance(
            job_id=resolved.job_id,
            process_id=decl.id,
            process_version=decl.version,
            backend={
                "name": "data-managers",
                "kind": "data-request",
                "sources": sorted({item.source for item in report.files}),
            },
        ),
    )
    records = _output_records(job, report)
    outcome = JobOutcome(
        job_id=resolved.job_id,
        process_id=decl.id,
        process_version=decl.version,
        status="successful",
        exit_code=0,
        started_at=started_at,
        finished_at=now(),
        outputs=records,
        warnings=tuple(warnings),
    )
    outcome.write(job)
    seal_job(job, job_id=resolved.job_id, inputset=inputset, outputs=records)
    return outcome


def _output_records(job: JobDirectory, report: Any) -> tuple[OutputRecord, ...]:
    """Hash the report, the input set when written, and every file the report lists."""
    records = []
    for output in DATA_REQUEST.outputs:
        if output.path == "outcome.json" or not job.resolve_output(output.path).is_file():
            continue
        records.append(_record(job, output.id, output.path, output.media_type, output.extra))
    for item in report.files:
        if item.path is None:
            continue
        relative = f"outputs/{item.path}"
        media_type = MEDIA_TYPES[Path(item.path).suffix]
        records.append(_record(job, Path(item.path).stem, relative, media_type, {}))
    return tuple(records)


def _record(
    job: JobDirectory, output_id: str, relative: str, media_type: str, extra: Any
) -> OutputRecord:
    digest, size = sha256_file(job.resolve_output(relative))
    return OutputRecord(
        id=output_id,
        path=relative,
        media_type=media_type,
        bytes=size,
        sha256=digest,
        extra=extra,
    )


def _build_inputset(resolved: _Resolved) -> InputSet:
    """Record what the job consumed: the question it asked, and the mask if any.

    The mask is its own resource, so the question carries its extent without it.
    """
    parameters = dict(resolved.effective_inputs)
    if resolved.mask_resource is not None:
        parameters["extent"] = {
            key: value for key, value in parameters["extent"].items() if key != "mask"
        }
    resources = [
        inline_resource(
            "request",
            role="parameters",
            value=parameters,
            pointer="/inputs",
        )
    ]
    if resolved.mask_resource is not None:
        resources.insert(0, resolved.mask_resource)
    return build_inputset(resources)


__all__ = [
    "CAPABILITY_ID",
    "CAPABILITY_VERSION",
    "DATA_REQUEST",
    "MEDIA_TYPES",
    "REACHED_HOSTS",
    "REPORT_PATH",
    "ExitCodeMapper",
    "run",
]
