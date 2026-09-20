"""Materialize one immutable regional flow stack for several catchments."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from hydromodpy.core.exceptions import JobUsageError, TerrainProductError
from hydromodpy.schema.job.digest import sha256_file
from hydromodpy.schema.job.directory import JobDirectory
from hydromodpy.schema.job.documents import read_document, write_document
from hydromodpy.schema.job.inputset import InputResource, build_inputset, inline_resource
from hydromodpy.schema.job.outcome import JobOutcome, OutputRecord, error_record, now
from hydromodpy.schema.job.provenance import build_provenance, write_provenance
from hydromodpy.schema.job.request import content_address
from hydromodpy.schema.job.reuse import reuse_sealed_outcome
from hydromodpy.schema.job.seal import seal_job, verify_job
from hydromodpy.schema.media_types import GEOTIFF_MEDIA_TYPE, JSON_MEDIA_TYPE
from hydromodpy.spatial.geographic.core.flow_products import (
    FlowProducts,
    build_regional_flow_products,
    flow_products_from_paths,
)
from hydromodpy.spatial.terrain import registry as terrain_registry

PROCESS_ID = "regional-flow-products"
PROCESS_VERSION = "1.0.0"
DESCRIPTION_PATH = "outputs/regional_flow.json"


class RegionalFlowRequest(BaseModel):
    """Inputs of a regional stack, independent of catchment outlets."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    dem_init_path: Path = Field(description="DEM actually used for routing, elevations in m.")
    dem_correc_type: Literal["fill", "breach"]
    crs_project: str | None = None
    engine_id: str = Field(default=terrain_registry.DEFAULT_ENGINE_ID, min_length=1)


@dataclass(frozen=True)
class RegionalFlowJob:
    """A verified flow stack and its materialization outcome."""

    job_dir: Path
    job_id: str
    products: FlowProducts
    outcome: JobOutcome


def _resolved(
    request: RegionalFlowRequest, *, backend: object | None = None
) -> tuple[dict[str, Any], str, int]:
    digest, size = sha256_file(request.dem_init_path)
    engine = terrain_registry.create(request.engine_id, backend=backend)
    inputs = {
        "dem_sha256": digest,
        "dem_correc_type": request.dem_correc_type,
        "crs_project": request.crs_project,
        "engine": {
            "name": engine.engine_id,
            "version": engine.engine_version,
            "digest": engine.engine_digest(),
        },
    }
    job_id = content_address(process_id=PROCESS_ID, process_version=PROCESS_VERSION, inputs=inputs)
    return inputs, job_id, size


def regional_flow_identity(
    *,
    dem_init_path: str | Path,
    dem_correc_type: str,
    crs_project: str | None = None,
    engine_id: str | None = None,
    backend: object | None = None,
) -> str:
    """Address the DEM bytes, correction, CRS and resolved engine build."""
    request = RegionalFlowRequest.model_validate(
        {
            "dem_init_path": Path(dem_init_path).expanduser().resolve(),
            "dem_correc_type": dem_correc_type,
            "crs_project": crs_project,
            "engine_id": terrain_registry.DEFAULT_ENGINE_ID if engine_id is None else engine_id,
        }
    )
    return _resolved(request, backend=backend)[1]


def load_regional_flow_job(
    *,
    job_dir: str | Path,
    expected_job_id: str | None = None,
    dem_init_path: str | Path | None = None,
    dem_correc_type: str | None = None,
    crs_project: str | None = None,
    engine_id: str | None = None,
    backend: object | None = None,
) -> RegionalFlowJob:
    """Read a sealed stack after verifying every published artifact."""
    if dem_init_path is not None:
        if dem_correc_type is None:
            raise ValueError("dem_correc_type is required when validating a routing DEM")
        addressed = regional_flow_identity(
            dem_init_path=dem_init_path,
            dem_correc_type=dem_correc_type,
            crs_project=crs_project,
            engine_id=engine_id,
            backend=backend,
        )
        if expected_job_id is not None and addressed != expected_job_id:
            raise JobUsageError("Regional flow inputs disagree with expected_job_id")
        expected_job_id = addressed
    job = JobDirectory.for_reading(job_dir)
    verification = verify_job(job)
    if not verification.ok:
        raise TerrainProductError(
            f"Regional flow job {job.root} cannot be reused: " + "; ".join(verification.problems)
        )
    request_document = read_document(job.resolve_output(DESCRIPTION_PATH))
    if request_document.get("process") != {"id": PROCESS_ID, "version": PROCESS_VERSION}:
        raise JobUsageError(f"Job {job.root} is not a {PROCESS_ID} {PROCESS_VERSION} job")
    request = RegionalFlowRequest.model_validate(request_document["inputs"])
    stored = JobOutcome.from_document(read_document(job.outcome_path))
    described_id = content_address(
        process_id=PROCESS_ID,
        process_version=PROCESS_VERSION,
        inputs=request_document["resolved_inputs"],
    )
    if described_id != stored.job_id:
        raise TerrainProductError(f"Regional flow description disagrees with job {stored.job_id}")
    if stored.status != "successful":
        raise TerrainProductError(f"Regional flow job {job.root} did not succeed")
    outcome = reuse_sealed_outcome(job, job_id=expected_job_id or stored.job_id)
    products = flow_products_from_paths(
        dem_out_dir_path=job.outputs_dir, dem_correc_type=request.dem_correc_type
    )
    return RegionalFlowJob(job.root, outcome.job_id, products, outcome)


def materialize_regional_flow_job(
    *,
    job_dir: str | Path,
    dem_init_path: str | Path,
    dem_correc_type: str,
    crs_project: str | None = None,
    engine_id: str | None = None,
    backend: object | None = None,
) -> RegionalFlowJob:
    """Build once or read the same sealed job; callers serialize submissions."""
    request = RegionalFlowRequest.model_validate(
        {
            "dem_init_path": Path(dem_init_path).expanduser().resolve(),
            "dem_correc_type": dem_correc_type,
            "crs_project": crs_project,
            "engine_id": terrain_registry.DEFAULT_ENGINE_ID if engine_id is None else engine_id,
        }
    )
    inputs, job_id, dem_bytes = _resolved(request, backend=backend)
    job = JobDirectory.create(job_dir)
    if job.is_sealed:
        return load_regional_flow_job(job_dir=job.root, expected_job_id=job_id)
    if job.request_path.exists():
        previous = read_document(job.request_path)
        if previous.get("inputs") != request.model_dump(mode="json"):
            raise JobUsageError(f"Unfinished regional flow job {job.root} names other inputs")
    job.ensure_workspace()
    write_document(
        job.request_path,
        {
            "process": {"id": PROCESS_ID, "version": PROCESS_VERSION},
            "inputs": request.model_dump(mode="json"),
        },
    )
    started_at = now()
    try:
        products = build_regional_flow_products(
            dem_init_path=request.dem_init_path,
            dem_out_dir_path=job.outputs_dir,
            dem_correc_type=request.dem_correc_type,
            crs_project=request.crs_project,
            engine_id=request.engine_id,
            backend=backend,
        )
        inputset = build_inputset(
            [
                InputResource(
                    name="dem",
                    role="dem",
                    href=str(request.dem_init_path),
                    media_type=GEOTIFF_MEDIA_TYPE,
                    bytes=dem_bytes,
                    sha256=inputs["dem_sha256"],
                ),
                inline_resource("parameters", role="parameters", value=inputs, pointer="/inputs"),
            ]
        )
        write_document(job.inputset_path, inputset.to_document())
        write_provenance(
            job,
            build_provenance(
                job_id=job_id,
                process_id=PROCESS_ID,
                process_version=PROCESS_VERSION,
                backend=inputs["engine"],
            ),
        )
        write_document(
            job.resolve_output(DESCRIPTION_PATH),
            {
                "process": {"id": PROCESS_ID, "version": PROCESS_VERSION},
                "inputs": request.model_dump(mode="json"),
                "resolved_inputs": inputs,
                "accumulation": {"units": "cells", "transform": "ln"},
                "pointer_convention": "d8_wbt",
            },
        )
        records = []
        for name, path in (
            ("corrected_dem", products.correc),
            ("flow_direction", products.direc),
            ("flow_accumulation", products.acc),
        ):
            digest, size = sha256_file(Path(path))
            records.append(
                OutputRecord(
                    id=name,
                    path=job.relative(path),
                    media_type=GEOTIFF_MEDIA_TYPE,
                    bytes=size,
                    sha256=digest,
                )
            )
        digest, size = sha256_file(job.resolve_output(DESCRIPTION_PATH))
        records.append(
            OutputRecord(
                id="regional_flow",
                path=DESCRIPTION_PATH,
                media_type=JSON_MEDIA_TYPE,
                bytes=size,
                sha256=digest,
            )
        )
        outcome = JobOutcome(
            job_id=job_id,
            process_id=PROCESS_ID,
            process_version=PROCESS_VERSION,
            status="successful",
            exit_code=0,
            started_at=started_at,
            finished_at=now(),
            outputs=tuple(records),
        )
        outcome.write(job)
        seal_job(job, job_id=job_id, inputset=inputset, outputs=records)
    except Exception as exc:
        JobOutcome(
            job_id=job_id,
            process_id=PROCESS_ID,
            process_version=PROCESS_VERSION,
            status="failed",
            exit_code=1,
            started_at=started_at,
            finished_at=now(),
            errors=(error_record(exc),),
        ).write(job)
        raise
    return RegionalFlowJob(job.root, job_id, products, outcome)
