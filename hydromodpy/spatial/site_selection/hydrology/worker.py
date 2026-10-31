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

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, cast

import geopandas as gpd
import pandas as pd

from hydromodpy.core.exceptions import (
    ConfigValidationError,
    DataContractViolation,
    EmptyCatchmentError,
)
from hydromodpy.core.io.geoparquet import write_geoparquet_atomic
from hydromodpy.schema.job.digest import sha256_file
from hydromodpy.schema.job.directory import JobDirectory
from hydromodpy.schema.job.extent import SpatialExtent
from hydromodpy.schema.job.inputset import (
    InputResource,
    InputSet,
    build_inputset,
    inline_resource,
)
from hydromodpy.schema.job.outcome import (
    JobOutcome,
)
from hydromodpy.schema.job.request import (
    check_process,
    content_address,
    read_request,
    requested_outputs,
    validate_inputs,
)
from hydromodpy.schema.job.worker import ExitCodeMapper, run_job, seal_successful
from hydromodpy.schema.media_types import GEOTIFF_MEDIA_TYPE
from hydromodpy.spatial.geographic.core.flow_products import (
    ACCUMULATION_NAME,
    DIRECTION_NAME,
    corrected_dem_name,
)
from hydromodpy.spatial.job_inputs import (
    output_records,
    read_raster_input,
    refuse_a_file_that_is_not_the_one_asked_for,
    resolve_input_file,
)
from hydromodpy.spatial.site_selection.config.dem_config import HydrologyConfig
from hydromodpy.spatial.site_selection.domain.candidate_outlet import CandidateOutlet
from hydromodpy.spatial.site_selection.domain.delineated_catchment import (
    DelineatedCatchment,
    outlet_snap_distance_m,
    snapped_outlet_xy,
)
from hydromodpy.spatial.site_selection.domain.watershed import read_watershed, watershed_area_m2
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
    delineate_site_selection_candidates,
)
from hydromodpy.spatial.site_selection.hydrology.flow_products import (
    build_site_selection_flow_products,
)
from hydromodpy.spatial.terrain import registry as terrain_registry

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
    dem_extent: SpatialExtent
    effective_inputs: dict[str, Any]
    job_id: str
    warnings: tuple[str, ...]


def run(job: JobDirectory, *, exit_code_for: ExitCodeMapper) -> JobOutcome:
    """Execute ``terrain-delineate`` inside *job* and return what happened.

    The loop is :func:`hydromodpy.schema.job.worker.run_job`. A directory
    already sealed under the same ``job_id`` is the same work and comes back
    reused; one sealed under a different id is refused, because running would
    overwrite a seal, a job id and a set of outputs that somebody else may
    already have read. Resolving the request first costs one pass over the DEM,
    which is what the content address is made of, and that is the whole price
    of the short-circuit: what it skips is the conditioning, the routing and
    the delineation.
    """
    return run_job(
        job,
        decl=TERRAIN_DELINEATE,
        resolve=_resolve,
        execute=_execute,
        exit_code_for=exit_code_for,
    )


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

    dem_path = resolve_input_file(job, inputs.dem.href, member="dem")
    dem_digest, dem_bytes = sha256_file(dem_path)
    refuse_a_file_that_is_not_the_one_asked_for(
        inputs.dem.sha256, digest=dem_digest, href=inputs.dem.href, member="dem"
    )
    dem_extent = dem_extent_of(inputs, path=dem_path)
    refuse_an_engine_this_installation_does_not_serve(inputs)

    effective_inputs = _effective_inputs(inputs, dem_digest=dem_digest)
    return _Resolved(
        inputs=inputs,
        dem_path=dem_path,
        dem_digest=dem_digest,
        dem_bytes=dem_bytes,
        dem_extent=dem_extent,
        effective_inputs=effective_inputs,
        job_id=content_address(
            process_id=decl.id,
            process_version=decl.version,
            inputs=effective_inputs,
        ),
        warnings=tuple(warnings),
    )


def _execute(job: JobDirectory, resolved: _Resolved, started_at: str) -> JobOutcome:
    """Do the work of a resolved request and seal what it produced."""
    job.ensure_workspace()
    # Before the work and not after it: naming the engine builds one, and a
    # constructor that raises must take down a job that has done nothing, not a
    # job that has computed every artefact and is about to seal them.
    backend = _backend_identity(resolved.inputs.engine)
    catchments = _produce(job, resolved.inputs, dem_path=resolved.dem_path)
    warnings = list(resolved.warnings)
    warnings.extend(
        f"outlet {catchment.site_id!r} was not delineated: {catchment.failure_reason}"
        for catchment in catchments
        if catchment.status != DELINEATED
    )
    return seal_successful(
        job,
        decl=TERRAIN_DELINEATE,
        job_id=resolved.job_id,
        inputset=terrain_inputset(
            dem_digest=resolved.dem_digest,
            dem_bytes=resolved.dem_bytes,
            dem_extent=resolved.dem_extent,
            inputs=resolved.inputs,
            effective_inputs=resolved.effective_inputs,
        ),
        backend=backend,
        outputs=lambda: output_records(job, TERRAIN_DELINEATE),
        warnings=tuple(warnings),
        started_at=started_at,
    )


def dem_extent_of(inputs: TerrainDelineateRequest, *, path: Path) -> SpatialExtent:
    """Measure the declared DEM, refusing one no raster reader opens as one band.

    The check is here, on the input, and not around the chain: a failure the
    engine raises is the backend failing, and a file that is not a raster is
    bad input.

    The extent is the raster bounds in ``crs_project``: the request declares
    the DEM in that CRS, and the chain stamps it on every product. A raster
    stored south-up reports its bounds inverted, so the box takes the min and
    the max of each axis. A raster whose geotransform covers no area is bad
    input too, and is refused the same way.
    """
    left, bottom, right, top = read_raster_input(
        inputs.dem.href, path=path, member="dem", read=lambda source: source.bounds
    )
    try:
        return SpatialExtent(
            bbox=(min(left, right), min(bottom, top), max(left, right), max(bottom, top)),
            crs=inputs.crs_project,
        )
    except ValueError as exc:
        raise DataContractViolation(
            f"input dem {inputs.dem.href!r} gives no valid extent in {inputs.crs_project!r}: {exc}"
        ) from exc


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
        engine_id=inputs.engine,
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
            engine_id=inputs.engine,
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
        parts = read_watershed(catchment.watershed_shp)
        snapped = snapped_outlet_xy(catchment)
        rows.append(
            {
                "site_id": catchment.site_id,
                "x_outlet": float(catchment.outlet.x),
                "y_outlet": float(catchment.outlet.y),
                "x_snapped": None if snapped is None else snapped[0],
                "y_snapped": None if snapped is None else snapped[1],
                "snap_distance_m": outlet_snap_distance_m(catchment),
                "area_m2": watershed_area_m2(parts),
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
    # RFC7946 leaves out the crs member that GDAL writes otherwise.
    frame.to_file(job.resolve_output(OUTLETS_SNAPPED_PATH), driver="GeoJSON", RFC7946="YES")


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


def terrain_inputset(
    *,
    dem_digest: str,
    dem_bytes: int,
    dem_extent: SpatialExtent,
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
                spatial=dem_extent,
            ),
            inline_resource(
                "parameters",
                role="parameters",
                value=parameters,
                pointer="/inputs",
            ),
        ]
    )


def refuse_an_engine_this_installation_does_not_serve(
    inputs: TerrainDelineateRequest,
) -> None:
    """Refuse an engine name nothing here can resolve, at the boundary.

    The name is a plain string because what it may hold depends on what is
    installed beside this build, so the model cannot refuse it and only the
    registry can. Doing it here, beside the two refusals about the DEM, is what
    keeps the failure at the edge: the alternative is a job that conditions a
    DEM, routes it, and dies on the delineation because nothing answers to the
    name it was given.

    Raised as :class:`ConfigValidationError` and not as the registry's own
    class: the capability declares it, it carries the exit code that means
    "your document is wrong", and it names the member that is wrong.
    """
    if terrain_registry.is_registered(inputs.engine):
        return
    served = ", ".join(terrain_registry.list_engine_ids()) or "none"
    raise ConfigValidationError(
        f"inputs.engine names {inputs.engine!r}, and this installation serves {served}. "
        f"A third-party engine joins that list through the "
        f"{terrain_registry.ENTRY_POINT_GROUP!r} entry-point group, without a patch to "
        "HydroModPy."
    )


def _backend_identity(engine_id: str) -> dict[str, Any]:
    """Name the engine that did the work, as the provenance records it.

    Built from the name the request carried, and not from a class this module
    imports: a provenance record that names a different engine than the one the
    job asked for is worse than none.

    It is a second instance of the engine, built only to read what it declares
    about itself, so its caller runs it before the work rather than after. A
    third-party constructor that fails then fails a job that has produced
    nothing.
    """
    engine = terrain_registry.create(engine_id)
    return {
        "name": engine.engine_id,
        "version": engine.engine_version,
        "digest": engine.engine_digest(),
    }


__all__ = [
    "dem_extent_of",
    "refuse_an_engine_this_installation_does_not_serve",
    "run",
    "terrain_inputset",
]
