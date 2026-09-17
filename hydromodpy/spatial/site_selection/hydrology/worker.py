"""``terrain-delineate``, executed: one job directory in, one seal out.

This is the first function of this repository that is a capability rather than
a step: it receives a directory, reads the only document the caller wrote,
does its work inside that directory and seals it. It opens no workspace, no
catalog and no database, it registers nothing in the user's state directory,
and it reaches no network. Nothing here knows it is a job in a queue.

What it binds over is deliberately not new: ``build_site_selection_flow_products``
and ``delineate_site_selection_candidates``, both already pure, keyword-only
and free of every layer above ``spatial``. What did not exist is a verb that
stops there.

Three shapes worth knowing before reading the code.

**The rasters are built straight into** ``outputs/`` **and renamed once.** The
chain names its files after what it did (``dem_fill.tif``, ``dem_breach.tif``),
and a declared output path cannot depend on an input, so the three rasters get
their declared names in place after the delineation has finished reading them.
Copying them would double the largest write of the job for nothing.

**The delineation works in a scratch directory and publishes three assembled
artefacts.** One directory per outlet holding a mask, a boundary and two point
layers is the shape the batch needs while it runs; what a caller asked for is
one catchment layer, one table and one set of snapped outlets. The scratch is
under ``TMPDIR``, which is why the declaration lists that variable.

**The exit code is the runtime's decision, not this function's.** ``run``
takes the mapper as an argument because ``spatial`` cannot import ``cli``, and
because the exception a capability raises and the status a shim reads are two
different contracts. The caller that owns the process owns the mapping.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, cast

import geopandas as gpd
import pandas as pd
import rasterio

from hydromodpy.core.exceptions import (
    DataContractViolation,
    EmptyCatchmentError,
    JobUsageError,
)
from hydromodpy.core.io.geoparquet import write_geoparquet_atomic
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
    check_process,
    content_address,
    read_request,
    requested_outputs,
    validate_inputs,
)
from hydromodpy.schema.job.seal import seal_job
from hydromodpy.schema.media_types import GEOTIFF_MEDIA_TYPE
from hydromodpy.spatial.geographic.core.flow_products import (
    ACCUMULATION_NAME,
    DIRECTION_NAME,
    corrected_dem_name,
)
from hydromodpy.spatial.site_selection.candidates.outlets import CandidateOutlet
from hydromodpy.spatial.site_selection.config import HydrologyConfig
from hydromodpy.spatial.site_selection.hydrology.capability import (
    DEM_CORRECTED_PATH,
    FLOW_ACCUMULATION_PATH,
    FLOW_DIRECTION_PATH,
    OUTLETS_SNAPPED_PATH,
    TERRAIN_DELINEATE,
    WATERSHED_TABLE_PATH,
    WATERSHED_VECTOR_PATH,
    TerrainDelineateRequest,
)
from hydromodpy.spatial.site_selection.hydrology.delineation import (
    DelineatedCatchment,
    outlet_snap_distance_m,
    snapped_outlet_xy,
)
from hydromodpy.spatial.site_selection.hydrology.flow_products import (
    build_site_selection_flow_products,
)
from hydromodpy.spatial.site_selection.hydrology.pipeline import (
    delineate_site_selection_candidates,
)
from hydromodpy.spatial.terrain.whitebox_engine import WhiteboxTerrainEngine

ExitCodeMapper = Callable[[BaseException], int]
"""How the runtime turns an exception into the status a shim reads."""

WATERSHED_LAYER = "watershed"
"""The layer name inside the GeoPackage. A GeoPackage without one is unnamed."""

GEOJSON_CRS = "EPSG:4326"
"""RFC 7946 knows one CRS. The projected coordinates stay as properties."""

DELINEATED = "delineated"
"""The status ``try_delineate_candidate_outlet`` gives an outlet that worked."""


@dataclass(frozen=True, slots=True)
class _Resolved:
    """What the request resolved to, before anything is written."""

    inputs: TerrainDelineateRequest
    dem_path: Path
    dem_digest: str
    dem_bytes: int
    effective_inputs: dict[str, Any]
    job_id: str
    warnings: tuple[str, ...]


def run(job: JobDirectory, *, exit_code_for: ExitCodeMapper) -> JobOutcome:
    """Execute ``terrain-delineate`` inside *job* and return what happened.

    Writes ``outcome.json`` in every case. Writes ``manifest.json`` only when
    the job succeeded and every declared output is on disk and hashed, which
    is the one invariant a caller outside this process relies on.

    Refuses a directory that is already sealed, before touching anything: the
    invocation contract gives one job one directory, and re-running over a
    finished one would overwrite a seal, a job id and a set of outputs that
    somebody else may already have read.
    """
    if job.is_sealed:
        # Raised outside the try on purpose. Turning this into a failed
        # outcome would overwrite the outcome of the job that did finish,
        # which is the very document this refusal exists to protect.
        raise JobUsageError(
            f"job directory {job.root} is already sealed; a job directory holds one job"
        )
    started_at = now()
    decl = TERRAIN_DELINEATE
    job_id = UNIDENTIFIED_JOB
    try:
        resolved = _resolve(job)
        job_id = resolved.job_id
        return _execute(job, resolved, started_at=started_at)
    except KeyboardInterrupt as exc:
        # TerminationRequested subclasses KeyboardInterrupt, so SIGTERM and
        # Ctrl+C unwind through the same branch. Nothing is sealed: a
        # cancelled directory is readable and explicitly unfinished.
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


def _resolve(job: JobDirectory) -> _Resolved:
    """Read and check the request, and address the work it asks for.

    Everything here happens before a byte is written into the job, so a
    refusal leaves the directory exactly as the caller staged it.
    """
    decl = TERRAIN_DELINEATE
    request = read_request(job)
    warnings = list(check_process(request, decl))
    warnings.extend(
        f"request carries the envelope member {member!r}, which this process ignores"
        for member in request.undeclared_members
    )
    inputs = cast(TerrainDelineateRequest, validate_inputs(request, decl))
    # Validated and not used to filter: transmission is by reference, so every
    # declared output is produced and sealed whatever the caller asked to hear
    # about. What this call is for is refusing an output name nobody declares,
    # before the run rather than after the seal.
    requested_outputs(request, decl)

    dem_path = _resolve_dem(job, inputs)
    dem_digest, dem_bytes = sha256_file(dem_path)
    _refuse_a_dem_that_is_not_the_one_asked_for(inputs, digest=dem_digest)
    _refuse_a_dem_that_is_not_a_raster(inputs, path=dem_path)

    effective_inputs = _effective_inputs(inputs, dem_digest=dem_digest)
    return _Resolved(
        inputs=inputs,
        dem_path=dem_path,
        dem_digest=dem_digest,
        dem_bytes=dem_bytes,
        effective_inputs=effective_inputs,
        job_id=content_address(
            process_id=decl.id,
            process_version=decl.version,
            inputs=effective_inputs,
        ),
        warnings=tuple(warnings),
    )


def _execute(job: JobDirectory, resolved: _Resolved, *, started_at: str) -> JobOutcome:
    """Do the work of a resolved request and seal what it produced."""
    decl = TERRAIN_DELINEATE
    job.ensure_workspace()
    catchments = _produce(job, resolved.inputs, dem_path=resolved.dem_path)
    warnings = list(resolved.warnings)
    warnings.extend(
        f"outlet {catchment.site_id!r} was not delineated: {catchment.failure_reason}"
        for catchment in catchments
        if catchment.status != DELINEATED
    )

    inputset = _build_inputset(
        dem_digest=resolved.dem_digest,
        dem_bytes=resolved.dem_bytes,
        inputs=resolved.inputs,
        effective_inputs=resolved.effective_inputs,
    )
    write_document(job.inputset_path, inputset.to_document())
    write_provenance(
        job,
        build_provenance(
            job_id=resolved.job_id,
            process_id=decl.id,
            process_version=decl.version,
            backend=_backend_identity(),
        ),
    )

    records = _output_records(job)
    outcome = JobOutcome(
        job_id=resolved.job_id,
        process_id=decl.id,
        process_version=decl.version,
        status="successful",
        # Not asked of the mapper: a success exits 0 by POSIX, and JobOutcome
        # refuses any other code beside this status, so the literal cannot drift.
        exit_code=0,
        started_at=started_at,
        finished_at=now(),
        outputs=records,
        warnings=tuple(warnings),
    )
    outcome.write(job)
    seal_job(job, job_id=resolved.job_id, inputset=inputset, outputs=records)
    return outcome


def _resolve_dem(job: JobDirectory, inputs: TerrainDelineateRequest) -> Path:
    """Resolve the declared DEM and prove it is there before anything runs."""
    dem_path = job.resolve_input(inputs.dem.href, loc=("inputs", "dem", "href"))
    if not dem_path.is_file():
        raise FileNotFoundError(
            f"input dem names {inputs.dem.href!r}, and {dem_path} is not a file"
        )
    return dem_path


def _refuse_a_dem_that_is_not_the_one_asked_for(
    inputs: TerrainDelineateRequest, *, digest: str
) -> None:
    """Refuse a DEM whose bytes are not the ones the request pinned."""
    declared = inputs.dem.sha256
    if declared is None:
        return
    if declared.lower() != digest:
        raise DataContractViolation(
            f"input dem {inputs.dem.href!r} hashes to {digest} and the request pinned "
            f"{declared.lower()}; the bytes are not the ones the job asked for"
        )


def _refuse_a_dem_that_is_not_a_raster(inputs: TerrainDelineateRequest, *, path: Path) -> None:
    """Refuse a declared DEM that no raster reader can open as one band.

    The check is here, on the input, and not around the chain: a failure the
    engine raises is the backend failing, and a file that is not a raster is
    bad input. Without it a text file handed as ``dem`` surfaced as an
    untyped ``HMPY.E000`` and exit 1, the code whose whole meaning is "this
    is a bug in HydroModPy, report it".
    """
    try:
        with rasterio.open(str(path)) as source:
            band_count = source.count
    except rasterio.errors.RasterioError as exc:
        raise DataContractViolation(
            f"input dem {inputs.dem.href!r} cannot be opened as a raster: {exc}"
        ) from exc
    except OSError as exc:
        raise DataContractViolation(f"input dem {inputs.dem.href!r} cannot be read: {exc}") from exc
    if band_count < 1:
        raise DataContractViolation(
            f"input dem {inputs.dem.href!r} carries {band_count} band(s); "
            "an elevation model carries at least one"
        )


def _effective_inputs(inputs: TerrainDelineateRequest, *, dem_digest: str) -> dict[str, Any]:
    """Return what the run really used, with the DEM replaced by its digest.

    Effective and not literal: two requests that differ only by an omitted
    default asked for the same work and must carry the same ``job_id``.
    """
    payload = inputs.model_dump(mode="json")
    payload["dem"] = {"sha256": dem_digest}
    return payload


def _produce(
    job: JobDirectory,
    inputs: TerrainDelineateRequest,
    *,
    dem_path: Path,
) -> list[DelineatedCatchment]:
    """Run the chain and leave the six declared artefacts in ``outputs/``."""
    outputs = job.outputs_dir
    flow = build_site_selection_flow_products(
        dem_init_path=dem_path,
        output_dir=outputs,
        hydrology=HydrologyConfig(hydrologic_conditioning=inputs.dem_correction_type),
        crs_project=inputs.crs_project,
    )
    candidates = [
        CandidateOutlet(
            candidate_id=outlet.site_id,
            x=outlet.x,
            y=outlet.y,
            crs=inputs.crs_project,
            source="request",
        )
        for outlet in inputs.outlets
    ]
    with TemporaryDirectory(prefix="hmp-terrain-delineate-") as scratch:
        catchments = delineate_site_selection_candidates(
            candidates,
            flow_products=flow,
            output_root=scratch,
            snap_dist_m=inputs.snap_distance_m,
            crs_project=inputs.crs_project,
        )
        delineated = [one for one in catchments if one.status == DELINEATED]
        if not delineated:
            raise EmptyCatchmentError(
                f"none of the {len(catchments)} declared outlet(s) delineated a catchment; "
                "check that they fall inside the DEM and widen snap_distance_m"
            )
        _write_watersheds(job, delineated, crs=inputs.crs_project)
        _write_outlet_roll_call(job, catchments, crs=inputs.crs_project)

    _rename_rasters(job, dem_correction_type=inputs.dem_correction_type)
    return catchments


def _watershed_frame(catchments: Sequence[DelineatedCatchment], *, crs: str) -> gpd.GeoDataFrame:
    """Assemble one row per delineated outlet, its parts dissolved into one."""
    rows = []
    for catchment in catchments:
        parts = gpd.read_file(str(catchment.watershed_shp))
        snapped = snapped_outlet_xy(catchment)
        rows.append(
            {
                "site_id": catchment.site_id,
                "x_outlet": float(catchment.outlet.x),
                "y_outlet": float(catchment.outlet.y),
                "x_snapped": None if snapped is None else snapped[0],
                "y_snapped": None if snapped is None else snapped[1],
                "snap_distance_m": outlet_snap_distance_m(catchment),
                "area_m2": float(parts.geometry.area.sum()),
                "geometry": parts.geometry.union_all(),
            }
        )
    return gpd.GeoDataFrame(pd.DataFrame(rows), geometry="geometry", crs=crs)


def _write_watersheds(
    job: JobDirectory, catchments: Sequence[DelineatedCatchment], *, crs: str
) -> None:
    """Publish the catchments as one GeoPackage layer and one GeoParquet."""
    frame = _watershed_frame(catchments, crs=crs)
    frame.to_file(job.resolve_output(WATERSHED_VECTOR_PATH), driver="GPKG", layer=WATERSHED_LAYER)
    write_geoparquet_atomic(frame, job.resolve_output(WATERSHED_TABLE_PATH))


def _write_outlet_roll_call(
    job: JobDirectory, catchments: Sequence[DelineatedCatchment], *, crs: str
) -> None:
    """Publish one feature per **declared** outlet, delineated or not.

    Every outlet the request named appears here, carrying ``status`` and,
    when it failed, ``failure_reason``. A batch of ten outlets of which three
    produced nothing is a legitimate success -- refusing the whole job over
    one bad coordinate would throw away the seven that worked -- but a caller
    must be able to find out which three, by reading an artefact rather than
    by parsing the prose of ``warnings``. That is why the roll call is this
    layer and not the catchment layer: a rejected outlet has no polygon.

    A rejected outlet's point is the coordinate the request declared, because
    it was never snapped to anything.
    """
    rows = []
    for catchment in catchments:
        snapped = snapped_outlet_xy(catchment)
        delineated = catchment.status == DELINEATED
        x, y = snapped if snapped is not None else (catchment.outlet.x, catchment.outlet.y)
        rows.append(
            {
                "site_id": catchment.site_id,
                "status": catchment.status,
                "failure_reason": catchment.failure_reason,
                "crs_project": crs,
                "x_outlet": float(catchment.outlet.x),
                "y_outlet": float(catchment.outlet.y),
                "x_snapped": float(x) if delineated else None,
                "y_snapped": float(y) if delineated else None,
                "snap_distance_m": outlet_snap_distance_m(catchment) if delineated else None,
            }
        )
    frame = gpd.GeoDataFrame(
        pd.DataFrame(rows),
        geometry=gpd.points_from_xy(
            [_or_declared(row, "x") for row in rows],
            [_or_declared(row, "y") for row in rows],
        ),
        crs=crs,
    ).to_crs(GEOJSON_CRS)
    frame.to_file(job.resolve_output(OUTLETS_SNAPPED_PATH), driver="GeoJSON")


def _or_declared(row: dict[str, Any], axis: str) -> float:
    """Return the snapped coordinate of a roll-call row, or the declared one."""
    snapped = row[f"{axis}_snapped"]
    return float(row[f"{axis}_outlet"] if snapped is None else snapped)


def _rename_rasters(job: JobDirectory, *, dem_correction_type: str) -> None:
    """Give the three rasters the names the declaration promises.

    Done after the delineation, which reads them at the names the chain
    writes. A declared path cannot depend on an input, and ``dem_fill.tif``
    and ``dem_breach.tif`` are two names for one output.
    """
    outputs = job.outputs_dir
    for written, declared in (
        (corrected_dem_name(dem_correction_type), DEM_CORRECTED_PATH),
        (DIRECTION_NAME, FLOW_DIRECTION_PATH),
        (ACCUMULATION_NAME, FLOW_ACCUMULATION_PATH),
    ):
        (outputs / written).replace(job.resolve_output(declared))


def _build_inputset(
    *,
    dem_digest: str,
    dem_bytes: int,
    inputs: TerrainDelineateRequest,
    effective_inputs: dict[str, Any],
) -> InputSet:
    """Record what the job consumed: one file, and the parameters that drove it.

    The parameters are one resource and not five, because ``request.json``
    holds them under one member and the pointer names that member. Their value
    is the effective one, defaults applied, which is what the run used and
    what the ``job_id`` addresses.

    The DEM record is assembled here rather than through ``file_resource``,
    which would open and hash the raster a second time: the digest this
    records is the one the request was checked against, read from the same
    bytes, and a DEM is routinely larger than memory.
    """
    parameters = dict(effective_inputs)
    parameters.pop("dem")
    return build_inputset(
        [
            InputResource(
                name="dem",
                role="dem",
                href=inputs.dem.href,
                media_type=inputs.dem.type or GEOTIFF_MEDIA_TYPE,
                bytes=dem_bytes,
                sha256=dem_digest,
                spatial={"crs": inputs.crs_project},
            ),
            inline_resource(
                "parameters",
                role="parameters",
                value=parameters,
                pointer="/inputs",
            ),
        ]
    )


def _output_records(job: JobDirectory) -> tuple[OutputRecord, ...]:
    """Hash every declared artefact that exists once the job has written it.

    ``outcome.json`` is declared and absent here: it cannot carry its own
    digest. The seal hashes it from disk, which is the only place its bytes
    can be read from.
    """
    records = []
    for output in TERRAIN_DELINEATE.outputs:
        if output.path == "outcome.json":
            continue
        path = job.resolve_output(output.path)
        digest, size = sha256_file(path)
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


def _backend_identity() -> dict[str, Any]:
    """Name the engine that did the work, as the provenance records it."""
    engine = WhiteboxTerrainEngine()
    return {
        "name": engine.engine_id,
        "version": engine.engine_version,
        "digest": engine.engine_digest(),
    }


__all__ = ["ExitCodeMapper", "run"]
