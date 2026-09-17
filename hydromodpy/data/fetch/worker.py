"""``data-fetch``, executed: one job directory in, one seal out.

The second capability of this repository, and the first that reaches a network.
It opens no workspace, no catalog and no database, it registers nothing in the
user's state directory, and it never sees a ``geographic`` object: what used to
be read off one -- the extent -- is a member of ``request.json``.

Three shapes worth knowing before reading the code.

**The source is built from the request, and the fetch is handed a scratch it
owns.** ``FetchRequest.out_dir`` is mandatory, so every fetch gets a
``TemporaryDirectory`` under ``TMPDIR`` whether its source writes there or not.
Only the one artefact the declaration names is moved under ``outputs/``, which
is why a run of the IGN source leaves no ``raw_ign/`` tree beside its raster.

**The report is written even when nothing came back.** A bbox over the sea has
no piezometer, and that is an answer rather than a failure: the run succeeds,
``outputs/fetch.json`` says ``"empty": true``, and the payload artefact is
absent -- which the declaration allows, every payload output carrying
``required=False``.

**The extent is resolved before anything is written.** A mask is opened, hashed
and reduced to its bounds during resolution, so a request naming a file that is
not a vector is refused with the job directory exactly as the caller staged it,
and the digest of those bytes is what the ``job_id`` addresses.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, cast

from hydromodpy.core.exceptions import (
    DataContractViolation,
    DataRequestError,
    JobUsageError,
)
from hydromodpy.data.fetch.artefacts import payload_summary, write_payload
from hydromodpy.data.fetch.capability import (
    DATA_FETCH,
    PAYLOAD_PATHS,
    REPORT_PATH,
    WATERSHED_MASK_LAYER_HINT,
    DataFetchRequest,
)
from hydromodpy.data.source.port import (
    DataSource,
    Extent,
    FetchRequest,
    FetchResult,
    Period,
)
from hydromodpy.schema.job.digest import sha256_file
from hydromodpy.schema.job.directory import JobDirectory
from hydromodpy.schema.job.documents import write_document
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

ExitCodeMapper = Callable[[BaseException], int]
"""How the runtime turns an exception into the status a shim reads."""

REPORT_SCHEMA = "hmp-fetch-report/v1"
"""What ``outputs/fetch.json`` is, named in the document itself."""


@dataclass(frozen=True, slots=True)
class _Resolved:
    """What the request resolved to, before anything is written."""

    inputs: DataFetchRequest
    source: DataSource
    extent: Extent | None
    period: Period | None
    mask_resource: InputResource | None
    effective_inputs: dict[str, Any]
    job_id: str
    warnings: tuple[str, ...]


def run(job: JobDirectory, *, exit_code_for: ExitCodeMapper) -> JobOutcome:
    """Execute ``data-fetch`` inside *job* and return what happened.

    Writes ``outcome.json`` in every case. Writes ``manifest.json`` only when
    the job succeeded, which is the one invariant a caller outside this process
    relies on.
    """
    if job.is_sealed:
        # Answered outside the try, for the reason terrain-delineate gives:
        # turning any of it into a failed outcome would overwrite the outcome of
        # the job that did finish.
        return _reuse_or_refuse(job)
    started_at = now()
    decl = DATA_FETCH
    job_id = UNIDENTIFIED_JOB
    try:
        resolved = _resolve(job)
        job_id = resolved.job_id
        return _execute(job, resolved, started_at=started_at)
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
    """Answer a directory that is already sealed, without writing into it.

    Resolving the request costs one read of the mask, when there is one, and no
    network at all: what the short-circuit skips is the fetch itself.
    """
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

    Everything here happens before a byte is written into the job, so a refusal
    leaves the directory exactly as the caller staged it. The source is built
    here too: the three options models refuse an option their adapter does not
    serve in their constructor, and that refusal belongs before the run.
    """
    decl = DATA_FETCH
    request = read_request(job)
    warnings = list(check_process(request, decl))
    warnings.extend(
        f"request carries the envelope member {member!r}, which this process ignores"
        for member in request.undeclared_members
    )
    inputs = cast(DataFetchRequest, validate_inputs(request, decl))
    # Validated and not used to filter, as terrain-delineate does: transmission
    # is by reference, so every artefact the run produces is sealed whatever the
    # caller asked to hear about. What this call refuses is an output name
    # nobody declares, before the run rather than after the seal.
    requested_outputs(request, decl)

    source = inputs.source.build()
    extent, mask_resource = _resolve_extent(job, inputs)
    period = (
        None if inputs.period is None else Period(start=inputs.period.start, end=inputs.period.end)
    )

    effective_inputs = _effective_inputs(inputs, mask_resource=mask_resource)
    return _Resolved(
        inputs=inputs,
        source=source,
        extent=extent,
        period=period,
        mask_resource=mask_resource,
        effective_inputs=effective_inputs,
        job_id=content_address(
            process_id=decl.id,
            process_version=decl.version,
            inputs=effective_inputs,
        ),
        warnings=tuple(warnings),
    )


def _resolve_extent(
    job: JobDirectory, inputs: DataFetchRequest
) -> tuple[Extent | None, InputResource | None]:
    """Turn whichever selector the request carries into an extent.

    A declared bounding box is one already. A mask is a file: it is hashed, its
    bounds are read, and the extent is those bounds in the CRS the file declares
    -- which is what makes ``terrain-delineate`` and this capability chain
    through a directory. A station list selects no extent at all.
    """
    if inputs.extent is not None:
        xmin, ymin, xmax, ymax = inputs.extent.bbox
        return (
            Extent(xmin=xmin, ymin=ymin, xmax=xmax, ymax=ymax, crs=inputs.extent.crs),
            None,
        )
    if inputs.mask is None:
        return None, None

    mask_path = job.resolve_input(inputs.mask.href, loc=("inputs", "mask", "href"))
    if not mask_path.is_file():
        raise FileNotFoundError(
            f"input mask names {inputs.mask.href!r}, and {mask_path} is not a file"
        )
    digest, size = sha256_file(mask_path)
    _refuse_a_mask_that_is_not_the_one_asked_for(inputs.mask, digest=digest)
    extent = _extent_of_mask(inputs.mask, path=mask_path)
    resource = InputResource(
        name="mask",
        role="extent",
        href=inputs.mask.href,
        media_type=inputs.mask.type,
        bytes=size,
        sha256=digest,
        spatial={"crs": extent.crs, "bbox": list(extent.bbox)},
    )
    return extent, resource


def _refuse_a_mask_that_is_not_the_one_asked_for(mask: FileLink, *, digest: str) -> None:
    """Refuse a mask whose bytes are not the ones the request pinned."""
    declared = mask.sha256
    if declared is None:
        return
    if declared.lower() != digest:
        raise DataContractViolation(
            f"input mask {mask.href!r} hashes to {digest} and the request pinned "
            f"{declared.lower()}; the bytes are not the ones the job asked for"
        )


def _extent_of_mask(mask: FileLink, *, path: Path) -> Extent:
    """Read the bounds and the CRS of a vector mask, refusing what has neither.

    The check is on the input and not around the fetch: a file no vector reader
    opens is bad input, and without this it surfaced as an untyped ``HMPY.E000``
    and exit 1 -- the code whose whole meaning is "this is a bug in HydroModPy".
    """
    import geopandas as gpd

    href = mask.href
    try:
        frame = gpd.read_file(str(path))
    except Exception as exc:
        raise DataRequestError(
            f"input mask {href!r} cannot be read as a vector file: {exc}. "
            f"Expected {WATERSHED_MASK_LAYER_HINT}."
        ) from exc
    if frame.crs is None:
        raise DataRequestError(
            f"input mask {href!r} declares no CRS, so the bounds it carries name no place"
        )
    if len(frame) == 0:
        raise DataRequestError(f"input mask {href!r} holds no feature, so it bounds nothing")
    xmin, ymin, xmax, ymax = (float(value) for value in frame.total_bounds)
    return Extent(xmin=xmin, ymin=ymin, xmax=xmax, ymax=ymax, crs=str(frame.crs))


def _effective_inputs(
    inputs: DataFetchRequest, *, mask_resource: InputResource | None
) -> dict[str, Any]:
    """Return what the run really asked for, the mask replaced by its digest.

    Effective and not literal, for the reason terrain-delineate gives: two
    requests that differ only by an omitted default asked for the same work and
    must carry the same ``job_id``. The mask becomes its digest so that two
    copies of one file under two names are one job, and so that the address does
    not move when an orchestrator stages the same mask somewhere else.
    """
    payload = inputs.model_dump(mode="json")
    if mask_resource is not None:
        payload["mask"] = {"sha256": mask_resource.sha256}
    return payload


def _execute(job: JobDirectory, resolved: _Resolved, *, started_at: str) -> JobOutcome:
    """Fetch what the request asked for and seal what came back."""
    decl = DATA_FETCH
    job.ensure_workspace()
    warnings = list(resolved.warnings)

    with TemporaryDirectory(prefix="hmp-data-fetch-") as scratch:
        result = resolved.source.fetch(
            FetchRequest(
                out_dir=Path(scratch),
                extent=resolved.extent,
                station_ids=tuple(resolved.inputs.station_ids),
                period=resolved.period,
            )
        )
        _publish(job, result, source=resolved.source)

    if result.is_empty:
        warnings.append(
            f"source {result.source_id!r} answered with an empty {result.kind} payload; "
            "the report is sealed and no data artefact is"
        )

    inputset = _build_inputset(resolved)
    write_document(job.inputset_path, inputset.to_document())
    write_provenance(
        job,
        build_provenance(
            job_id=resolved.job_id,
            process_id=decl.id,
            process_version=decl.version,
            backend=_backend_identity(resolved.source),
        ),
    )

    records = _output_records(job)
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


def _publish(job: JobDirectory, result: FetchResult, *, source: DataSource) -> None:
    """Write the report and, when there is one, the payload artefact.

    Called **inside** the scratch's lifetime, because a ``files`` payload is a
    path into it and is moved rather than copied. What ended up on disk is read
    back off the directory by :func:`_output_records`, not carried out of here:
    two lists of what a run produced are two chances to disagree.
    """
    written = [REPORT_PATH]
    if not result.is_empty:
        payload_path = PAYLOAD_PATHS[result.kind]
        write_payload(result, job.resolve_output(payload_path))
        written.append(payload_path)
    write_document(
        job.resolve_output(REPORT_PATH),
        _report(result, source=source, written=tuple(written)),
    )


def _report(result: FetchResult, *, source: DataSource, written: tuple[str, ...]) -> dict[str, Any]:
    """Describe what came back, in the one artefact every run produces.

    It carries the extent that was **really queried**, in the CRS it was really
    queried in, which is the port's central claim and the one thing a caller
    cannot recover from the payload: a WGS84 box asked for a DEM reaches the
    Geoplateforme in Lambert-93 metres, and nothing else on disk says so.

    It also names the **hosts** this run contacted, and not only the source id.
    The capability declares the union of the four providers it may reach,
    because that is what an orchestrator has to allow before it has read the
    request; which of them a given run actually reached is a different question,
    and this is the artefact that answers it. Reading it off the source id would
    mean shipping the source-to-host table beside the job directory.
    """
    extent = result.extent
    period = result.period
    return {
        "schema": REPORT_SCHEMA,
        "source": result.source_id,
        "hosts": list(source.hosts),
        "payload_kind": result.kind,
        "variables": list(result.variables),
        "empty": result.is_empty,
        "queried_extent": (
            None if extent is None else {"bbox": list(extent.bbox), "crs": extent.crs}
        ),
        "queried_period": (
            None
            if period is None
            else {"start": period.start.isoformat(), "end": period.end.isoformat()}
        ),
        "counts": payload_summary(result),
        "artifacts": [path for path in written if path != REPORT_PATH],
        "source_metadata": _jsonable(result.metadata),
    }


def _jsonable(metadata: dict[str, object]) -> dict[str, Any]:
    """Render a source's own metadata, falling back to its text form.

    A source declares what it puts here and nothing constrains it to JSON
    scalars -- ``Sim2PrecipitationSource`` reports a tuple of components. A
    member that does not serialise is rendered as its ``repr`` rather than
    dropped: losing it silently would make the report claim a source said
    nothing about itself.
    """
    rendered: dict[str, Any] = {}
    for key, value in metadata.items():
        try:
            json.dumps(value)
        except TypeError:
            rendered[str(key)] = repr(value)
        else:
            rendered[str(key)] = value
    return rendered


def _build_inputset(resolved: _Resolved) -> InputSet:
    """Record what the job consumed: the question it asked, and the mask if any.

    The question is one inline resource and not five, because ``request.json``
    holds it under one member and the pointer names that member. Its value is
    the effective one, defaults applied and the mask reduced to its digest,
    which is what the ``job_id`` addresses.
    """
    parameters = dict(resolved.effective_inputs)
    parameters.pop("mask", None)
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


def _output_records(job: JobDirectory) -> tuple[OutputRecord, ...]:
    """Hash every declared artefact that is on disk once the run has written it.

    ``outcome.json`` is declared and skipped: it cannot carry its own digest,
    and the seal hashes it from disk, which is the only place its bytes can be
    read from. Everything else is included **if it exists**, which is what makes
    this different from ``terrain-delineate``: the four payload outputs are
    declared ``required=False`` and a run writes exactly one of them.

    Existence and not a list of what was produced: ``inputset.json`` is a
    declared output too, written by this function's caller a few lines above,
    and a version of this that walked the payload list alone left it out of
    ``outcome.json`` while the seal still carried it -- two documents of one
    directory disagreeing about what the job produced.
    """
    records = []
    for output in DATA_FETCH.outputs:
        if output.path == "outcome.json" or not job.resolve_output(output.path).is_file():
            continue
        digest, size = sha256_file(job.resolve_output(output.path))
        records.append(
            OutputRecord(
                id=output.id,
                path=output.path,
                media_type=output.media_type,
                bytes=size,
                sha256=digest,
                extra=output.extra,
            )
        )
    return tuple(records)


def _backend_identity(source: DataSource) -> dict[str, Any]:
    """Name what did the work, as the provenance records it.

    No version, and that is the honest answer rather than a missing one: the
    backend of this capability is a remote service, and none of the four
    endpoints this tree calls publishes a version of the dataset it served. What
    can be recorded is which adapter asked, in which CRS, and of which host.
    """
    return {
        "name": source.source_id,
        "kind": "data-source",
        "extent_crs": source.extent_crs,
        "hosts": list(source.hosts),
    }


__all__ = ["REPORT_SCHEMA", "ExitCodeMapper", "run"]
