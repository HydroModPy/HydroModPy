"""Materialize shared regional flow jobs for a regional lab."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import rasterio

from hydromodpy.analysis.testbed.regional_lab_types import RegionalLabPlannedCase
from hydromodpy.config.hydromodpy_config import HydroModPyConfig
from hydromodpy.core.exceptions import ConfigError
from hydromodpy.core.toml_io.io import dump_toml_with_comments
from hydromodpy.spatial.geographic.regional_flow_job import (
    materialize_regional_flow_job,
    regional_flow_identity,
)


@dataclass(frozen=True)
class RegionalLabMaterialization:
    """Child configs and measured regional job outcomes."""

    cases: tuple[RegionalLabPlannedCase, ...]
    report: dict[str, Any]


def _effective_crs(dem_path: Path, configured: str | None) -> str | None:
    if configured is not None:
        return configured
    with rasterio.open(dem_path) as dem:
        epsg = dem.crs.to_epsg() if dem.crs is not None else None
    return f"EPSG:{epsg}" if epsg is not None else None


def materialize_regional_lab_flow(
    cases: Sequence[RegionalLabPlannedCase], *, output_root: Path
) -> RegionalLabMaterialization:
    """Share one sealed flow stack among eligible child simulations."""
    jobs_root = output_root / "regional_flow_jobs"
    configs_root = output_root / "materialized_configs"
    configs_root.mkdir(parents=True, exist_ok=True)
    resolved_cases: list[RegionalLabPlannedCase] = []
    job_records: dict[str, dict[str, Any]] = {}
    case_inputs: dict[str, dict[str, str]] = {}
    identities: dict[tuple[Path, str, str | None, str | None], str] = {}
    for case in cases:
        if case.launcher != "simulation":
            raise ConfigError("Shared regional flow requires simulation recipes")
        config = HydroModPyConfig.from_toml(case.config_path)
        config_hash = hashlib.sha256(
            json.dumps(config.model_dump(mode="json"), sort_keys=True).encode("utf-8")
        ).hexdigest()
        geographic = config.geographic
        if geographic.catch_def != "from_outlet_coord":
            raise ConfigError(f"{case.case_id}: shared flow requires an outlet catchment")
        if geographic.dem_init_path is None:
            raise ConfigError(f"{case.case_id}: shared flow requires a DEM path")
        if geographic.enforce_lakes.enabled or geographic.enforce_streams.enabled:
            raise ConfigError(f"{case.case_id}: outlet-dependent routing cannot share flow")
        if geographic.river_network.enabled:
            raise ConfigError(
                f"{case.case_id}: shared river-network products are not yet materialized"
            )
        crs_project = _effective_crs(geographic.dem_init_path, geographic.crs_project)

        identity_key = (
            geographic.dem_init_path.resolve(),
            geographic.dem_correc_type,
            crs_project,
            geographic.terrain_engine,
        )
        if identity_key not in identities:
            identities[identity_key] = regional_flow_identity(
                dem_init_path=geographic.dem_init_path,
                dem_correc_type=geographic.dem_correc_type,
                crs_project=crs_project,
                engine_id=geographic.terrain_engine,
            )
        job_id = identities[identity_key]
        job_dir = jobs_root / job_id
        if job_id not in job_records:
            job = materialize_regional_flow_job(
                job_dir=job_dir,
                dem_init_path=geographic.dem_init_path,
                dem_correc_type=geographic.dem_correc_type,
                crs_project=crs_project,
                engine_id=geographic.terrain_engine,
            )
            job_records[job_id] = {
                "job_id": job_id,
                "job_dir": str(job_dir.resolve()),
                "reused": bool(job.outcome.reused),
                "case_ids": [],
            }
        geographic.reg_fold = job_dir.resolve()
        case_inputs[case.case_id] = {"config_hash": config_hash, "regional_flow_job_id": job_id}
        case_digest = hashlib.sha256(case.case_id.encode("utf-8")).hexdigest()[:32]
        materialized_path = configs_root / f"case-{case_digest}.toml"
        dump_toml_with_comments(config, materialized_path, profile="expert")
        resolved_cases.append(replace(case, config_path=materialized_path))
        job_records[job_id]["case_ids"].append(case.case_id)

    jobs = list(job_records.values())
    return RegionalLabMaterialization(
        cases=tuple(resolved_cases),
        report={
            "job_count": len(jobs),
            "executed_job_count": sum(not job["reused"] for job in jobs),
            "reused_job_count": sum(job["reused"] for job in jobs),
            "jobs": jobs,
            "case_inputs": case_inputs,
        },
    )
