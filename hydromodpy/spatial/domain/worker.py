"""``domain-build``, executed: a terrain and a depth model in, a geometry out.

The body calls :func:`hydromodpy.spatial.domain.build.build_domain`, the
constructor a run uses, so the sealed geometry is the one a run builds.

Every output lands on the grid of the DEM, which is never resampled nor
clipped. The mask only decides which cells are active: it is projected onto the
CRS of the DEM before it is burned. A substratum raster is reprojected onto the
grid of the DEM. The job runs on no engine, so its provenance names no backend.
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
from hydromodpy.core.io.raster_io import write_band
from hydromodpy.core.nodata import valid_cells
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
from hydromodpy.spatial.domain.depth_model_config import RASTER_DEPTH_MODEL_KINDS
from hydromodpy.spatial.domain.domain_config import DomainConfig
from hydromodpy.spatial.geographic.core.surface_from_dem import build_surface_topo_from_dem
from hydromodpy.spatial.job_inputs import (
    output_records,
    read_raster_input,
    refuse_a_file_that_is_not_the_one_asked_for,
)
from hydromodpy.spatial.surface import Surface

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
    substratum_path: Path | None
    substratum_digest: str | None
    substratum_bytes: int | None
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
    refuse_a_file_that_is_not_the_one_asked_for(
        inputs.dem.sha256, digest=dem_digest, href=inputs.dem.href, member="dem"
    )
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

    mask_path = mask_digest = mask_bytes = mask_layer = None
    if inputs.mask is not None:
        mask_path = _resolve_file(job, inputs.mask.href, member="mask")
        mask_digest, mask_bytes = sha256_file(mask_path)
        refuse_a_file_that_is_not_the_one_asked_for(
            inputs.mask.sha256, digest=mask_digest, href=inputs.mask.href, member="mask"
        )
        mask_layer = _resolve_mask_layer(mask_path, declared=inputs.mask_layer)
    elif inputs.mask_layer is not None:
        raise refuse_request(
            "mask_layer names a layer and no mask file is declared",
            loc=("inputs", "mask_layer"),
            msg="declare a mask, or drop mask_layer",
        )

    substratum_path = substratum_digest = substratum_bytes = None
    reads_a_raster = inputs.depth_model.kind in RASTER_DEPTH_MODEL_KINDS
    if inputs.substratum is not None:
        if not reads_a_raster:
            raise refuse_request(
                f"substratum names a raster, and depth_model kind "
                f"{inputs.depth_model.kind!r} reads none",
                loc=("inputs", "substratum"),
                msg="drop substratum, or use a raster depth model kind",
            )
        substratum_path = _resolve_file(job, inputs.substratum.href, member="substratum")
        substratum_digest, substratum_bytes = sha256_file(substratum_path)
        refuse_a_file_that_is_not_the_one_asked_for(
            inputs.substratum.sha256,
            digest=substratum_digest,
            href=inputs.substratum.href,
            member="substratum",
        )
        warnings.extend(
            _check_a_raster_input(
                inputs.substratum.href,
                path=substratum_path,
                member="substratum",
                why_a_crs="it is reprojected onto the grid of the dem",
            )
        )
    elif reads_a_raster:
        raise refuse_request(
            f"depth_model kind {inputs.depth_model.kind!r} reads the substratum raster, "
            "and the request declares none",
            loc=("inputs", "substratum"),
            msg="declare the substratum raster",
        )

    effective_inputs = _effective_inputs(
        inputs,
        dem_digest=dem_digest,
        mask_digest=mask_digest,
        mask_layer=mask_layer,
        substratum_digest=substratum_digest,
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

    records = output_records(job, decl)
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


def _produce(job: JobDirectory, resolved: _Resolved) -> None:
    """Build the geometry and leave the four declared artefacts in ``outputs/``."""
    inputs = resolved.inputs
    surface_topo = build_surface_topo_from_dem(resolved.dem_path)
    top = surface_topo.as_array()
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
    # The mask is the extent here: a substratum raster has to cover the active
    # cells, not the whole terrain the mask cuts them out of.
    substratum_source = (
        None
        if resolved.substratum_path is None
        else Surface.from_raster(resolved.substratum_path, name="substratum_source")
    )
    try:
        domain = build_domain(
            DomainConfig(depth_model=inputs.depth_model),
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

    bottom = domain.substratum.as_array()
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
    grid = {
        "driver": "GTiff",
        "height": top.shape[0],
        "width": top.shape[1],
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
    # Exact equality on the sentinel: ``Surface.shifted_down_by`` leaves it in
    # place rather than shifting it, precisely so this comparison holds.
    active = valid_cells(top, nodata)
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
                # The raster a ``raster`` depth model read, by input and digest
                # like the top; null for a depth model that reads none.
                "substratum": (
                    None
                    if resolved.substratum_digest is None
                    else {"input": "substratum", "sha256": resolved.substratum_digest}
                ),
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


__all__ = ["ExitCodeMapper", "run"]
