"""``domain-build``, executed: a terrain and a depth model in, a geometry out.

The body binds over :func:`hydromodpy.spatial.domain.build.build_domain`, which
is the same constructor the setup step of a run calls and the same one a run
that redefines its domain calls. That is the whole point of the phase: four
sites construct a domain today, and a capability that reimplemented the
vertical extent would be a fifth spelling of it, sealing an artefact provably
unrelated to what a run does.

What is new here is everything around it -- reading a terrain off disk,
bounding the grid, and writing the geometry down so that something which never
held the object can read it.

Three shapes worth knowing before reading the code.

**The grid is the DEM's grid, and every output lands on it.** No resampling, no
reprojection, no clipping to the mask: the mask decides which cells are active,
not which cells exist. A consumer that lines the four rasters up cell by cell
is doing the right thing, and that is worth more than a tighter bounding box.

**Only the mask is reprojected.** A polygon in another CRS is projected onto
the DEM's before it is burned, because that is a lossless operation on a
boundary, while reprojecting the terrain would resample elevations and silently
change the geometry the caller asked for.

**The job runs on no engine.** Its provenance carries no backend: the
arithmetic is the depth model and the readers are the ones the environment
already records package by package. A backend record naming ``rasterio`` would
add nothing the frozen package list does not already carry, and would suggest a
substitutable engine where there is none.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.features import rasterize

from hydromodpy.core.exceptions import DataContractViolation, JobUsageError
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
from hydromodpy.schema.job.refusal import refuse_request
from hydromodpy.schema.job.request import (
    check_process,
    content_address,
    read_request,
    requested_outputs,
    validate_inputs,
)
from hydromodpy.schema.job.reuse import reuse_sealed_outcome
from hydromodpy.schema.job.seal import seal_job
from hydromodpy.schema.media_types import GEOPACKAGE_MEDIA_TYPE, GEOTIFF_MEDIA_TYPE
from hydromodpy.spatial.domain.build import build_domain
from hydromodpy.spatial.domain.capability import (
    ACTIVE_CELLS_PATH,
    BOTTOM_PATH,
    DOMAIN_BUILD,
    DOMAIN_DOCUMENT_PATH,
    DOMAIN_SCHEMA,
    THICKNESS_PATH,
    DomainBuildRequest,
)
from hydromodpy.spatial.domain.domain_config import DomainConfig
from hydromodpy.spatial.geographic.core.surface_from_dem import build_surface_topo_from_dem

ExitCodeMapper = Callable[[BaseException], int]
"""How the runtime turns an exception into the status a shim reads."""

ACTIVE = 1
INACTIVE = 0
"""The two values of ``active_cells.tif``, as the declaration publishes them."""

POLYGONAL_TYPES = frozenset({"Polygon", "MultiPolygon"})
"""The geometry types a mask may be made of."""


@dataclass(frozen=True, slots=True)
class _Resolved:
    """What the request resolved to, before anything is written."""

    inputs: DomainBuildRequest
    dem_path: Path
    dem_digest: str
    dem_bytes: int
    mask_path: Path | None
    mask_digest: str | None
    mask_bytes: int | None
    mask_layer: str | None
    effective_inputs: dict[str, Any]
    job_id: str
    warnings: tuple[str, ...]

    @property
    def mask_target(self) -> tuple[Path, str] | None:
        """The mask file and the layer it resolved to, or nothing.

        The pair, never the two apart: a path without a resolved layer is a
        state :func:`_resolve` cannot produce, and what reads it should not have
        to admit one.
        """
        if self.mask_path is None or self.mask_layer is None:
            return None
        return (self.mask_path, self.mask_layer)


def run(job: JobDirectory, *, exit_code_for: ExitCodeMapper) -> JobOutcome:
    """Execute ``domain-build`` inside *job* and return what happened.

    Writes ``outcome.json`` in every case. Writes ``manifest.json`` only when
    the job succeeded and every declared output is on disk and hashed, which
    is the one invariant a caller outside this process relies on.

    A directory that is already sealed is answered before anything is touched,
    under the rule the whole family keeps: the same ``job_id`` is the same
    work and comes back reused, a different one is refused rather than
    overwritten.
    """
    if job.is_sealed:
        # Answered outside the try, for the reason terrain-delineate gives:
        # turning any of it into a failed outcome would overwrite the outcome
        # of the job that did finish.
        return _reuse_or_refuse(job)
    started_at = now()
    decl = DOMAIN_BUILD
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
    decl = DOMAIN_BUILD
    request = read_request(job)
    warnings = list(check_process(request, decl))
    warnings.extend(
        f"request carries the envelope member {member!r}, which this process ignores"
        for member in request.undeclared_members
    )
    inputs = cast(DomainBuildRequest, validate_inputs(request, decl))
    # Validated and not used to filter, as terrain-delineate does: every
    # declared output is produced whatever the caller asked to hear about, and
    # what this call is for is refusing an output name nobody declares.
    requested_outputs(request, decl)

    dem_path = _resolve_file(job, inputs.dem.href, member="dem")
    dem_digest, dem_bytes = sha256_file(dem_path)
    _refuse_a_file_that_is_not_the_one_asked_for(
        inputs.dem.sha256, digest=dem_digest, href=inputs.dem.href, member="dem"
    )
    warnings.extend(_check_the_terrain_the_domain_will_stand_on(inputs.dem.href, path=dem_path))

    mask_path = mask_digest = mask_bytes = mask_layer = None
    if inputs.mask is not None:
        mask_path = _resolve_file(job, inputs.mask.href, member="mask")
        mask_digest, mask_bytes = sha256_file(mask_path)
        _refuse_a_file_that_is_not_the_one_asked_for(
            inputs.mask.sha256, digest=mask_digest, href=inputs.mask.href, member="mask"
        )
        mask_layer = _resolve_mask_layer(mask_path, declared=inputs.mask_layer)
    elif inputs.mask_layer is not None:
        raise refuse_request(
            "mask_layer names a layer and no mask file is declared",
            loc=("inputs", "mask_layer"),
            msg="declare a mask, or drop mask_layer",
        )

    effective_inputs = _effective_inputs(
        inputs, dem_digest=dem_digest, mask_digest=mask_digest, mask_layer=mask_layer
    )
    return _Resolved(
        inputs=inputs,
        dem_path=dem_path,
        dem_digest=dem_digest,
        dem_bytes=dem_bytes,
        mask_path=mask_path,
        mask_digest=mask_digest,
        mask_bytes=mask_bytes,
        mask_layer=mask_layer,
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
    decl = DOMAIN_BUILD
    job.ensure_workspace()
    _produce(job, resolved)

    inputset = _build_inputset(resolved)
    write_document(job.inputset_path, inputset.to_document())
    write_provenance(
        job,
        build_provenance(
            job_id=resolved.job_id,
            process_id=decl.id,
            process_version=decl.version,
            # No backend: nothing here is an engine somebody could swap.
            backend=None,
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
        warnings=resolved.warnings,
    )
    outcome.write(job)
    seal_job(job, job_id=resolved.job_id, inputset=inputset, outputs=records)
    return outcome


def _resolve_file(job: JobDirectory, href: str, *, member: str) -> Path:
    """Resolve one declared file and prove it is there before anything runs."""
    path = job.resolve_input(href, loc=("inputs", member, "href"))
    if not path.is_file():
        raise FileNotFoundError(f"input {member} names {href!r}, and {path} is not a file")
    return path


def _refuse_a_file_that_is_not_the_one_asked_for(
    declared: str | None, *, digest: str, href: str, member: str
) -> None:
    """Refuse a file whose bytes are not the ones the request pinned."""
    if declared is None:
        return
    if declared.lower() != digest:
        raise DataContractViolation(
            f"input {member} {href!r} hashes to {digest} and the request pinned "
            f"{declared.lower()}; the bytes are not the ones the job asked for"
        )


def _check_the_terrain_the_domain_will_stand_on(href: str, *, path: Path) -> tuple[str, ...]:
    """Refuse a terrain no grid can be read off, and warn about what was ignored.

    The checks are on the input and not around the build: a file that is not a
    raster, a raster carrying no CRS, a grid no axis-aligned cell size describes
    -- each one is bad input, and without this they surfaced as an untyped
    ``HMPY.E000`` and exit 1, the code whose whole meaning is "this is a bug in
    HydroModPy, report it".
    """
    try:
        with rasterio.open(str(path)) as source:
            band_count = source.count
            crs = source.crs
            transform = source.transform
    except rasterio.errors.RasterioError as exc:
        raise DataContractViolation(
            f"input dem {href!r} cannot be opened as a raster: {exc}"
        ) from exc
    except OSError as exc:
        raise DataContractViolation(f"input dem {href!r} cannot be read: {exc}") from exc
    if band_count < 1:
        raise DataContractViolation(
            f"input dem {href!r} carries {band_count} band(s); "
            "an elevation model carries at least one"
        )
    if crs is None:
        raise DataContractViolation(
            f"input dem {href!r} carries no CRS, and the domain is built on its grid; "
            "the working CRS of this capability is the one the terrain declares"
        )
    if transform.b or transform.d:
        # A rotated or sheared grid has no ``dx`` and no ``dy``: the cell size is
        # ``sqrt(a**2 + b**2)`` along one axis and the cell area is
        # ``abs(a*e - b*d)``. Refused rather than described with the two numbers
        # this document would otherwise publish, and refused rather than
        # supported because ``build_surface_topo_from_dem`` derives its bounds
        # from ``a`` and ``e`` alone and would place the surface wrong.
        raise DataContractViolation(
            f"input dem {href!r} carries a rotated or sheared transform "
            f"(b={transform.b}, d={transform.d}); the domain is built on an "
            "axis-aligned grid, so reproject the terrain to a north-up one first"
        )
    if band_count == 1:
        return ()
    return (
        f"input dem {href!r} carries {band_count} bands; band 1 is read as the "
        "top surface and the others are ignored",
    )


def _effective_inputs(
    inputs: DomainBuildRequest,
    *,
    dem_digest: str,
    mask_digest: str | None,
    mask_layer: str | None,
) -> dict[str, Any]:
    """Return what the run really used, each file replaced by its digest.

    Effective and not literal: two requests that differ only by an omitted
    default asked for the same work and must carry the same ``job_id``. That is
    why *mask_layer* is the layer that was **resolved** and not the one that was
    written: a file holding one layer is read the same way whether the request
    named it or left the choice to the file.
    """
    payload = inputs.model_dump(mode="json")
    payload["dem"] = {"sha256": dem_digest}
    payload["mask"] = None if mask_digest is None else {"sha256": mask_digest}
    payload["mask_layer"] = mask_layer
    return payload


def _produce(job: JobDirectory, resolved: _Resolved) -> None:
    """Build the geometry and leave the four declared artefacts in ``outputs/``."""
    inputs = resolved.inputs
    surface_topo = build_surface_topo_from_dem(resolved.dem_path)
    try:
        domain = build_domain(
            DomainConfig(depth_model=inputs.depth_model),
            surface_topo=surface_topo,
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

    top = surface_topo.as_array()
    bottom = domain.substratum.as_array()
    with rasterio.open(str(resolved.dem_path)) as source:
        transform = source.transform
        crs = source.crs
        bounds = source.bounds
        nodata = source.nodata

    active = _active_cells(
        top,
        nodata=nodata,
        mask=resolved.mask_target,
        transform=transform,
        crs=crs,
    )
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

    # The grid of the terrain, and nothing else of its file. Inheriting the
    # whole ``profile`` would carry its compression across too, and a float
    # predictor kept over a uint8 band is a raster GDAL refuses to write.
    grid = {"height": top.shape[0], "width": top.shape[1], "crs": crs, "transform": transform}
    _write_raster(job, BOTTOM_PATH, bottom, grid=grid, dtype="float64", nodata=float("nan"))
    _write_raster(job, THICKNESS_PATH, thickness, grid=grid, dtype="float64", nodata=float("nan"))
    _write_raster(
        job,
        ACTIVE_CELLS_PATH,
        np.where(active, ACTIVE, INACTIVE),
        grid=grid,
        dtype="uint8",
        nodata=None,
    )
    write_document(
        job.resolve_output(DOMAIN_DOCUMENT_PATH),
        _domain_document(
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


def _active_cells(
    top: np.ndarray,
    *,
    nodata: float | None,
    mask: tuple[Path, str] | None,
    transform: Any,
    crs: Any,
) -> np.ndarray:
    """Return the boolean grid of cells the domain is defined on."""
    active = np.isfinite(top)
    if nodata is not None:
        # Exact equality, which is how every consumer of a HydroModPy raster
        # recognises the sentinel: ``Surface.shifted_down_by`` leaves it in
        # place rather than shifting it, precisely so this comparison holds.
        active &= top != float(nodata)
    if mask is not None:
        mask_path, mask_layer = mask
        active &= _burned_mask(
            mask_path, layer=mask_layer, shape=top.shape, transform=transform, crs=crs
        )
    if not bool(active.any()):
        raise DataContractViolation(
            "no cell of the terrain is active: the declared mask selects none of it, "
            "or the raster carries nothing but its nodata value"
        )
    return active


def _resolve_mask_layer(mask_path: Path, *, declared: str | None) -> str:
    """Return the layer the mask will be read from, refusing an unusable choice.

    Resolved in :func:`_resolve`, before a byte is written, for two reasons. A
    layer nobody can read is a request fault and the caller should learn it with
    the directory still as they staged it. And the *resolved* name is what the
    ``job_id`` is taken over: a file holding one layer is read the same way
    whether the request named it or left the choice to the file, so the two
    submissions are one job.
    """
    try:
        layers = [str(name) for name in gpd.list_layers(mask_path)["name"]]
    except Exception as exc:
        # Broad on purpose: pyogrio, fiona and GDAL each raise their own type
        # for "this is not a vector dataset", and the answer is the same one.
        raise DataContractViolation(
            f"mask {mask_path.name} cannot be opened as a vector dataset: {exc}"
        ) from exc
    if not layers:
        raise DataContractViolation(f"mask {mask_path.name} holds no layer at all")
    if declared is None:
        if len(layers) > 1:
            raise refuse_request(
                f"mask {mask_path.name} holds {len(layers)} layers "
                f"({', '.join(sorted(layers))}) and the request names none",
                loc=("inputs", "mask_layer"),
                msg="name the layer to read",
            )
        return layers[0]
    if declared not in layers:
        raise refuse_request(
            f"mask {mask_path.name} holds no layer named {declared!r}; "
            f"it holds {', '.join(sorted(layers))}",
            loc=("inputs", "mask_layer"),
            msg=f"unknown layer {declared!r}",
        )
    return declared


def _burned_mask(
    mask_path: Path,
    *,
    layer: str,
    shape: tuple[int, ...],
    transform: Any,
    crs: Any,
) -> np.ndarray:
    """Burn the resolved polygon layer onto the terrain grid."""
    frame = gpd.read_file(mask_path, layer=layer)
    if frame.crs is None:
        raise DataContractViolation(
            f"mask {mask_path.name} carries no CRS, so it cannot be placed on the terrain"
        )
    if crs is not None and frame.crs != crs:
        frame = frame.to_crs(crs)
    geometries = [geometry for geometry in frame.geometry if geometry is not None]
    if not geometries:
        raise DataContractViolation(
            f"layer {layer!r} of mask {mask_path.name} holds no geometry to bound the domain"
        )
    # A mask bounds an area, so it is made of areas. Without this, a line layer
    # burns a one-cell-wide diagonal and a point layer burns a single cell, and
    # both come back as a successful job with a domain that is a sliver --
    # which is what pointing ``mask`` at a hydrographic network instead of a
    # catchment produces, and the two live side by side in the same project.
    not_areas = sorted({geometry.geom_type for geometry in geometries} - POLYGONAL_TYPES)
    if not_areas:
        raise DataContractViolation(
            f"layer {layer!r} of mask {mask_path.name} holds {', '.join(not_areas)} geometries; "
            "the mask bounds an area and is read as polygons"
        )
    burned = rasterize(
        geometries,
        out_shape=shape,
        transform=transform,
        fill=INACTIVE,
        default_value=ACTIVE,
        all_touched=False,
        dtype="uint8",
    )
    return burned.astype(bool)


def _write_raster(
    job: JobDirectory,
    relative: str,
    values: np.ndarray,
    *,
    grid: dict[str, Any],
    dtype: str,
    nodata: float | None,
) -> None:
    """Write one band onto the terrain's own grid."""
    with rasterio.open(
        str(job.resolve_output(relative)),
        "w",
        driver="GTiff",
        count=1,
        dtype=dtype,
        nodata=nodata,
        **grid,
    ) as sink:
        sink.write(np.asarray(values, dtype=dtype), 1)


def _statistics(values: np.ndarray, active: np.ndarray) -> dict[str, float | None]:
    """Return the extent of *values* over the active cells, or nulls."""
    selected = np.asarray(values, dtype=float)[active]
    selected = selected[np.isfinite(selected)]
    if selected.size == 0:
        return {"min": None, "max": None, "mean": None}
    return {
        "min": float(np.min(selected)),
        "max": float(np.max(selected)),
        "mean": float(np.mean(selected)),
    }


def _domain_document(
    resolved: _Resolved,
    *,
    crs: Any,
    transform: Any,
    bounds: Any,
    nodata: float | None,
    top: np.ndarray,
    bottom: np.ndarray,
    thickness: np.ndarray,
    active: np.ndarray,
) -> dict[str, Any]:
    """Return the document a mesh generator is handed instead of a live object.

    Every statistic is taken over the **active** cells and says so. A mean over
    the whole grid would average the nodata sentinel into an elevation, which
    is what makes this document worth writing rather than deriving.
    """
    decl = DOMAIN_BUILD
    nrows, ncols = (int(top.shape[0]), int(top.shape[1]))
    cell_area = abs(float(transform.a) * float(transform.e))
    active_count = int(np.count_nonzero(active))
    return {
        "schema": DOMAIN_SCHEMA,
        "process": {"id": decl.id, "version": decl.version},
        "crs": crs.to_string(),
        "grid": {
            "nrows": nrows,
            "ncols": ncols,
            "dx": abs(float(transform.a)),
            "dy": abs(float(transform.e)),
            "bounds": {
                "xmin": float(bounds.left),
                "ymin": float(bounds.bottom),
                "xmax": float(bounds.right),
                "ymax": float(bounds.top),
            },
            "transform": [float(value) for value in tuple(transform)[:6]],
            "nodata": None if nodata is None else float(nodata),
        },
        "depth_model": resolved.inputs.depth_model.model_dump(mode="json"),
        "layers": [
            {
                "index": 0,
                # The top is an input and not an artefact of this job: naming
                # the resource of ``inputset.json`` is what lets a reader find
                # the digest of the raster the bottom was derived from.
                "top": {"input": "dem", "sha256": resolved.dem_digest},
                "bottom": BOTTOM_PATH,
                "thickness": THICKNESS_PATH,
            }
        ],
        "active_cells": {
            "path": ACTIVE_CELLS_PATH,
            "count": active_count,
            "total": nrows * ncols,
            "area_m2": active_count * cell_area,
            # The input and its digest, never its href: the mask lives outside
            # the job by construction, and a document that named the path it
            # sat at on the machine that built it would describe that machine.
            "mask": (
                None
                if resolved.mask_digest is None
                else {"input": "mask", "sha256": resolved.mask_digest}
            ),
        },
        "statistics": {
            "over": "active_cells",
            "top": _statistics(top, active),
            "bottom": _statistics(bottom, active),
            "thickness": _statistics(thickness, active),
        },
    }


def _build_inputset(resolved: _Resolved) -> InputSet:
    """Record what the job consumed: one or two files, and the parameters."""
    parameters = dict(resolved.effective_inputs)
    parameters.pop("dem")
    parameters.pop("mask")
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
    return build_inputset(resources)


def _output_records(job: JobDirectory) -> tuple[OutputRecord, ...]:
    """Hash every declared artefact that exists once the job has written it.

    ``outcome.json`` is declared and absent here: it cannot carry its own
    digest. The seal hashes it from disk, which is the only place its bytes
    can be read from.
    """
    records = []
    for output in DOMAIN_BUILD.outputs:
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


__all__ = ["ExitCodeMapper", "run"]
