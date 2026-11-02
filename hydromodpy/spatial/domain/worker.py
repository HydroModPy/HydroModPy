"""``domain-build``, executed: a terrain and a depth model in, a geometry out.

The body calls :func:`hydromodpy.spatial.domain.build.build_domain`, the
constructor a run uses, so the sealed geometry is the one a run builds.

Every output lands on the grid of the DEM, which is never resampled nor
clipped. The mask only decides which cells are active: it is projected onto the
CRS of the DEM before it is burned. A substratum raster is reprojected onto the
grid of the DEM. The job runs on no engine, so its provenance names no backend.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import numpy as np
import rasterio

from hydromodpy.core.exceptions import DataContractViolation
from hydromodpy.core.io.raster_io import write_band
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
    JobOutcome,
)
from hydromodpy.schema.job.refusal import refuse_request
from hydromodpy.schema.job.request import (
    FileLink,
    check_process,
    content_address,
    read_request,
    requested_outputs,
    validate_inputs,
)
from hydromodpy.schema.job.worker import ExitCodeMapper, run_job, seal_successful
from hydromodpy.schema.media_types import GEOPACKAGE_MEDIA_TYPE, GEOTIFF_MEDIA_TYPE
from hydromodpy.spatial.domain.active_cells import (
    ACTIVE,
    INACTIVE,
    active_cell_mask,
    resolve_mask_layer,
)
from hydromodpy.spatial.domain.build import build_domain
from hydromodpy.spatial.domain.capability import (
    ACTIVE_CELLS_PATH,
    BOTTOM_PATH,
    DOMAIN_BUILD,
    DOMAIN_DOCUMENT_PATH,
    THICKNESS_PATH,
    DomainBuildRequest,
)
from hydromodpy.spatial.domain.depth_model_config import RASTER_DEPTH_MODEL_KINDS
from hydromodpy.spatial.domain.domain_config import DomainConfig
from hydromodpy.spatial.domain.domain_document import ResolvedDomainRequest, build_domain_document
from hydromodpy.spatial.geographic.core.surface_from_dem import build_surface_topo_from_dem
from hydromodpy.spatial.job_inputs import (
    output_records,
    read_raster_input,
    refuse_a_file_that_is_not_the_one_asked_for,
    resolve_input_file,
)
from hydromodpy.spatial.surface import Surface


def run(job: JobDirectory, *, exit_code_for: ExitCodeMapper) -> JobOutcome:
    """Execute ``domain-build`` inside *job* and return what happened.

    The loop is :func:`hydromodpy.schema.job.worker.run_job`: a sealed
    directory is reused or refused, a failure becomes a failed outcome.
    """
    return run_job(
        job, decl=DOMAIN_BUILD, resolve=_resolve, execute=_execute, exit_code_for=exit_code_for
    )


def _resolve(job: JobDirectory) -> ResolvedDomainRequest:
    """Read and check the request, and address the work it asks for.

    Everything here happens before a byte is written into the job, so a
    refusal leaves the directory exactly as the caller staged it.
    """
    decl = DOMAIN_BUILD
    inputs, warnings = _read_inputs(job)
    dem_path, dem_digest, dem_bytes = _staged_file(job, inputs.dem, member="dem")
    warnings.extend(
        _check_a_raster_input(
            inputs.dem.href,
            path=dem_path,
            member="dem",
            why_a_crs=(
                "the domain is built on its grid; the working CRS of this capability "
                "is the one the terrain declares"
            ),
        )
    )
    mask_path, mask_digest, mask_bytes, mask_layer = _resolve_mask(job, inputs)
    substratum_path, substratum_digest, substratum_bytes, substratum_warnings = _resolve_substratum(
        job, inputs
    )
    warnings.extend(substratum_warnings)

    effective_inputs = _effective_inputs(
        inputs,
        dem_digest=dem_digest,
        mask_digest=mask_digest,
        mask_layer=mask_layer,
        substratum_digest=substratum_digest,
    )
    return ResolvedDomainRequest(
        inputs=inputs,
        dem_path=dem_path,
        dem_digest=dem_digest,
        dem_bytes=dem_bytes,
        mask_path=mask_path,
        mask_digest=mask_digest,
        mask_bytes=mask_bytes,
        mask_layer=mask_layer,
        substratum_path=substratum_path,
        substratum_digest=substratum_digest,
        substratum_bytes=substratum_bytes,
        effective_inputs=effective_inputs,
        job_id=content_address(
            process_id=decl.id,
            process_version=decl.version,
            inputs=effective_inputs,
        ),
        warnings=tuple(warnings),
    )


def _read_inputs(job: JobDirectory) -> tuple[DomainBuildRequest, list[str]]:
    """Read the request, check its envelope and return its inputs and warnings."""
    decl = DOMAIN_BUILD
    request = read_request(job)
    warnings = list(check_process(request, decl))
    warnings.extend(
        f"request carries the envelope member {member!r}, which this process ignores"
        for member in request.undeclared_members
    )
    inputs = cast(DomainBuildRequest, validate_inputs(request, decl))
    # Validated and not used to filter: every
    # declared output is produced whatever the caller asked to hear about, and
    # what this call is for is refusing an output name nobody declares.
    requested_outputs(request, decl)
    return inputs, warnings


def _staged_file(job: JobDirectory, link: FileLink, *, member: str) -> tuple[Path, str, int]:
    """Return the path, digest and size of one declared file, refusing a wrong one."""
    path = resolve_input_file(job, link.href, member=member)
    digest, size = sha256_file(path)
    refuse_a_file_that_is_not_the_one_asked_for(
        link.sha256, digest=digest, href=link.href, member=member
    )
    return path, digest, size


def _resolve_mask(
    job: JobDirectory, inputs: DomainBuildRequest
) -> tuple[Path | None, str | None, int | None, str | None]:
    """Return the mask file, its digest, its size and its layer, or four nulls."""
    mask_path = mask_digest = mask_bytes = mask_layer = None
    if inputs.mask is not None:
        mask_path, mask_digest, mask_bytes = _staged_file(job, inputs.mask, member="mask")
        mask_layer = resolve_mask_layer(mask_path, declared=inputs.mask_layer)
    elif inputs.mask_layer is not None:
        raise refuse_request(
            "mask_layer names a layer and no mask file is declared",
            loc=("inputs", "mask_layer"),
            msg="declare a mask, or drop mask_layer",
        )
    return mask_path, mask_digest, mask_bytes, mask_layer


def _resolve_substratum(
    job: JobDirectory, inputs: DomainBuildRequest
) -> tuple[Path | None, str | None, int | None, tuple[str, ...]]:
    """Return the substratum file, its digest, its size and its warnings.

    The depth model decides: a raster kind needs the file, any other refuses it.
    """
    substratum_path = substratum_digest = substratum_bytes = None
    warnings: tuple[str, ...] = ()
    reads_a_raster = inputs.depth_model.kind in RASTER_DEPTH_MODEL_KINDS
    if inputs.substratum is not None:
        if not reads_a_raster:
            raise refuse_request(
                f"substratum names a raster, and depth_model kind "
                f"{inputs.depth_model.kind!r} reads none",
                loc=("inputs", "substratum"),
                msg="drop substratum, or use a raster depth model kind",
            )
        substratum_path, substratum_digest, substratum_bytes = _staged_file(
            job, inputs.substratum, member="substratum"
        )
        warnings = _check_a_raster_input(
            inputs.substratum.href,
            path=substratum_path,
            member="substratum",
            why_a_crs="it is reprojected onto the grid of the dem",
        )
    elif reads_a_raster:
        raise refuse_request(
            f"depth_model kind {inputs.depth_model.kind!r} reads the substratum raster, "
            "and the request declares none",
            loc=("inputs", "substratum"),
            msg="declare the substratum raster",
        )
    return substratum_path, substratum_digest, substratum_bytes, warnings


def _execute(job: JobDirectory, resolved: ResolvedDomainRequest, started_at: str) -> JobOutcome:
    """Do the work of a resolved request and seal what it produced."""
    job.ensure_workspace()
    _produce(job, resolved)
    return seal_successful(
        job,
        decl=DOMAIN_BUILD,
        job_id=resolved.job_id,
        inputset=_build_inputset(resolved),
        # No backend: nothing here is an engine somebody could swap.
        backend=None,
        outputs=lambda: output_records(job, DOMAIN_BUILD),
        warnings=resolved.warnings,
        started_at=started_at,
    )


def _check_a_raster_input(href: str, *, path: Path, member: str, why_a_crs: str) -> tuple[str, ...]:
    """Refuse a raster no grid can be read off, and warn about what was ignored.

    A raster carrying no CRS, or a grid no axis-aligned cell size describes, is
    bad input like a file that is not a raster. The terrain and the substratum
    both go through it; *why_a_crs* says what the CRS of that one is needed for.
    """
    crs, transform, band_count = read_raster_input(
        href,
        path=path,
        member=member,
        read=lambda source: (source.crs, source.transform, source.count),
    )
    if crs is None:
        raise DataContractViolation(f"input {member} {href!r} carries no CRS, and {why_a_crs}")
    if transform.b or transform.d:
        # A rotated or sheared grid has no ``dx`` and no ``dy``: the cell size is
        # ``sqrt(a**2 + b**2)`` along one axis and the cell area is
        # ``abs(a*e - b*d)``. Refused rather than described with the two numbers
        # this document would otherwise publish, and refused rather than
        # supported because ``Surface.from_raster`` derives its bounds from
        # ``a`` and ``e`` alone and would place the surface wrong.
        raise DataContractViolation(
            f"input {member} {href!r} carries a rotated or sheared transform "
            f"(b={transform.b}, d={transform.d}); the domain is built on an "
            "axis-aligned grid, so reproject it to a north-up one first"
        )
    if band_count == 1:
        return ()
    return (
        f"input {member} {href!r} carries {band_count} bands; band 1 is read "
        "and the others are ignored",
    )


def _effective_inputs(
    inputs: DomainBuildRequest,
    *,
    dem_digest: str,
    mask_digest: str | None,
    mask_layer: str | None,
    substratum_digest: str | None,
) -> dict[str, Any]:
    """Return what the run really used, each file replaced by its digest.

    Effective and not literal: two requests that differ only by an omitted
    default asked for the same work and must carry the same ``job_id``. That is
    why *mask_layer* is the layer that was **resolved** and not the one that was
    written: a file holding one layer is read the same way whether the request
    named it or left the choice to the file.

    A request without a substratum carries no ``substratum`` key at all, so
    every ``job_id`` sealed before the member existed still names the same work.
    """
    payload = inputs.model_dump(mode="json")
    payload["dem"] = {"sha256": dem_digest}
    payload["mask"] = None if mask_digest is None else {"sha256": mask_digest}
    payload["mask_layer"] = mask_layer
    if substratum_digest is None:
        payload.pop("substratum")
    else:
        payload["substratum"] = {"sha256": substratum_digest}
    return payload


def _produce(job: JobDirectory, resolved: ResolvedDomainRequest) -> None:
    """Build the geometry and leave the four declared artefacts in ``outputs/``."""
    surface_topo = build_surface_topo_from_dem(resolved.dem_path)
    top = surface_topo.as_array()
    with rasterio.open(str(resolved.dem_path)) as source:
        transform = source.transform
        crs = source.crs
        bounds = source.bounds
        nodata = source.nodata

    active = active_cell_mask(
        top,
        nodata=nodata,
        mask=resolved.mask_target,
        transform=transform,
        crs=crs,
    )
    bottom = _substratum_elevation(resolved, surface_topo=surface_topo, active=active)
    # NaN outside the domain, on both elevation rasters. There is no aquifer
    # where the cell is inactive, and every other spelling of that publishes a
    # number: the DEM's own sentinel is not preserved by ``flat_like``, which
    # clamps a nodata cell to ``top - min_gap`` rather than leaving it at
    # ``-9999``, and it does not mark a cell the mask excluded at all. A finite
    # sentinel could not be used even if it were carried through, because a flat
    # substratum at 0 m on a terrain whose nodata is 0 would make every active
    # cell read as no data. NaN cannot collide with an elevation.
    bottom = np.where(active, bottom, np.nan)
    thickness = np.where(active, top - bottom, np.nan)

    _write_rasters(
        job,
        shape=top.shape,
        crs=crs,
        transform=transform,
        bottom=bottom,
        thickness=thickness,
        active=active,
    )
    write_document(
        job.resolve_output(DOMAIN_DOCUMENT_PATH),
        build_domain_document(
            resolved,
            crs=crs,
            transform=transform,
            bounds=bounds,
            nodata=nodata,
            top=top,
            bottom=bottom,
            thickness=thickness,
            active=active,
        ),
    )


def _substratum_elevation(
    resolved: ResolvedDomainRequest, *, surface_topo: Surface, active: np.ndarray
) -> np.ndarray:
    """Build the domain under the terrain and return its substratum elevation."""
    # The mask is the extent here: a substratum raster has to cover the active
    # cells, not the whole terrain the mask cuts them out of.
    substratum_source = (
        None
        if resolved.substratum_path is None
        else Surface.from_raster(resolved.substratum_path, name="substratum_source")
    )
    try:
        domain = build_domain(
            DomainConfig(depth_model=resolved.inputs.depth_model),
            surface_topo=surface_topo,
            substratum_source=substratum_source,
            active_cells=active,
        )
    except ValueError as exc:
        # A depth model the terrain leaves no aquifer under: ``flat_like``
        # refuses a substratum sitting at or above every finite cell. It is the
        # caller's number that is wrong, and without this the refusal surfaced
        # as an untyped ``HMPY.E000`` and exit 1 -- the code whose whole meaning
        # is "this is a bug in HydroModPy, report it".
        raise refuse_request(
            f"the declared depth model leaves no aquifer under this terrain: {exc}",
            loc=("inputs", "depth_model"),
            msg="no aquifer would remain under this terrain",
        ) from exc
    if domain.substratum is None:
        raise DataContractViolation(
            "the depth model produced no substratum, so the domain has no vertical extent"
        )
    return domain.substratum.as_array()


def _write_rasters(
    job: JobDirectory,
    *,
    shape: tuple[int, ...],
    crs: Any,
    transform: Any,
    bottom: np.ndarray,
    thickness: np.ndarray,
    active: np.ndarray,
) -> None:
    """Write the bottom, the thickness and the active cells on the grid of the DEM."""
    # The grid of the terrain, and nothing else of its file. Inheriting the
    # whole ``profile`` would carry its compression across too, and a float
    # predictor kept over a uint8 band is a raster GDAL refuses to write.
    grid = {
        "driver": "GTiff",
        "height": shape[0],
        "width": shape[1],
        "crs": crs,
        "transform": transform,
    }
    for relative, values, dtype, nodata_value in (
        (BOTTOM_PATH, bottom, "float64", float("nan")),
        (THICKNESS_PATH, thickness, "float64", float("nan")),
        (ACTIVE_CELLS_PATH, np.where(active, ACTIVE, INACTIVE), "uint8", None),
    ):
        write_band(
            job.resolve_output(relative),
            np.asarray(values, dtype=dtype),
            grid,
            dtype=dtype,
            nodata=nodata_value,
        )


def _build_inputset(resolved: ResolvedDomainRequest) -> InputSet:
    """Record what the job consumed: one to three files, and the parameters."""
    parameters = dict(resolved.effective_inputs)
    parameters.pop("dem")
    parameters.pop("mask")
    parameters.pop("substratum", None)
    resources = [
        InputResource(
            name="dem",
            role="dem",
            href=resolved.inputs.dem.href,
            media_type=resolved.inputs.dem.type or GEOTIFF_MEDIA_TYPE,
            bytes=resolved.dem_bytes,
            sha256=resolved.dem_digest,
        ),
        inline_resource(
            "parameters",
            role="parameters",
            value=parameters,
            pointer="/inputs",
        ),
    ]
    if resolved.inputs.mask is not None:
        resources.insert(
            1,
            InputResource(
                name="mask",
                role="mask",
                href=resolved.inputs.mask.href,
                media_type=resolved.inputs.mask.type or GEOPACKAGE_MEDIA_TYPE,
                bytes=resolved.mask_bytes,
                sha256=resolved.mask_digest,
            ),
        )
    if resolved.inputs.substratum is not None:
        resources.insert(
            len(resources) - 1,
            InputResource(
                name="substratum",
                role="substratum",
                href=resolved.inputs.substratum.href,
                media_type=resolved.inputs.substratum.type or GEOTIFF_MEDIA_TYPE,
                bytes=resolved.substratum_bytes,
                sha256=resolved.substratum_digest,
            ),
        )
    return build_inputset(resources)


__all__ = [
    "run",
]
