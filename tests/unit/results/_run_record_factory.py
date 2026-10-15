"""One sealed-run record, small enough to build in a test and complete enough to read back."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from hydromodpy.results.checks import CalibratedBy, Checks, Validity
from hydromodpy.results.identity import Identity
from hydromodpy.results.lineage import Lineage
from hydromodpy.results.manifest import (
    InputEntry,
    ManifestConfig,
    ManifestGeometry,
    ManifestPeriod,
    ManifestRun,
    ManifestSite,
    MetricRow,
    ParameterRow,
    TrackedInput,
)
from hydromodpy.results.metric_rule import DateWindow, MetricScore
from hydromodpy.results.record import RunProvenance, RunRecord

SIM_ID = "9a4f0000-0000-4000-8000-000000000001"
ATTEMPT_ID = "7c1e0000000000000000000000000001"
SITE = "J0014010"
CASE_ID = "J0014010-base"
FINGERPRINT = "abcd1234abcd1234"
CONFIG_HASH = "c0ffee" * 10 + "c0ff"
MESH_HASH = "mesh0001"
VERSION = "2.0.0a5"
NOW = datetime(2026, 10, 15, 8, 2, 11, tzinfo=UTC)
WINDOW = DateWindow(start=date(2016, 1, 1), end=date(2020, 12, 31))


def make_identity(**overrides: Any) -> Identity:
    """The identity block of the record, label-free."""
    payload: dict[str, Any] = {
        "site": SITE,
        "site_fingerprint": FINGERPRINT,
        "case_id": CASE_ID,
        "sim_id": SIM_ID,
        "attempt_id": ATTEMPT_ID,
        "config_hash": CONFIG_HASH,
        "mesh_hash": MESH_HASH,
        "period": WINDOW,
        "score_window": WINDOW,
        "hydromodpy_version": VERSION,
        "code_reproducible": False,
    }
    payload.update(overrides)
    return Identity(**payload)


def make_checks(**overrides: Any) -> Checks:
    """Checks of a promoted run whose budget closes."""
    payload: dict[str, Any] = {
        "budget_pct": 0.8,
        "budget_threshold_pct": 2.0,
        "converged": True,
        "obs_coverage": 0.97,
        "score_window": WINDOW,
        "n_samples": 1827,
        "calibrated_by": CalibratedBy(
            session_id="sess0001", phase="transient_sy", trial=7, session_status="completed"
        ),
        "validities": [Validity("water_budget", True, 0.8, "the water balance closes", True)],
        "bounds_hit": [],
        "code_reproducible": False,
    }
    payload.update(overrides)
    return Checks(**payload)


def make_record(**overrides: Any) -> RunRecord:
    """A complete record of a promoted, scored run of the Nancon."""
    payload: dict[str, Any] = {
        "run": ManifestRun(
            sim_id=SIM_ID,
            name="J0014010-base.v2",
            name_stem=CASE_ID,
            version=2,
            status="completed",
            project="bretagne_k",
            case_id=CASE_ID,
            recipe="base",
            rel_dir="runs/J0014010-base.v2",
            attempt=2,
            attempt_id=ATTEMPT_ID,
            solver="modflow6",
            solver_category="groundwater",
            flow_regime="transient",
            created_at=NOW,
            started_at=NOW,
            ended_at=NOW,
            duration_s=1049.0,
            description="Nancon, daily",
        ),
        "site": ManifestSite(
            name=SITE,
            label="Nancon",
            gauge="J0014010",
            uri="hubeau:J0014010",
            fingerprint=FINGERPRINT,
            x_outlet=350000.0,
            y_outlet=6800000.0,
            crs="EPSG:2154",
            area_km2=65.2,
            dem_resolution_m=75.0,
            snapped_outlet=(350012.0, 6800003.0),
        ),
        "geometry": ManifestGeometry(
            n_cells=4148,
            n_layers=1,
            mesh_topology="voronoi",
            mesh_engine="voronoi",
            mesh_engine_version="1",
            mesh_hash=MESH_HASH,
            crs_wkt="EPSG:2154",
            crs_epsg=2154,
            bbox=(340000.0, 6790000.0, 360000.0, 6810000.0),
            catchment={"catch_area": 65.2, "dem_res": 75.0},
        ),
        "period": ManifestPeriod(
            start=datetime(2016, 1, 1, tzinfo=UTC),
            end=datetime(2020, 12, 31, tzinfo=UTC),
            n_timesteps=1827,
            time_unit="day",
        ),
        "config": ManifestConfig(file="config.toml", hash=CONFIG_HASH, source="project.toml"),
        "lineage": Lineage(
            session_id="sess0001",
            phase="transient_sy",
            trial=7,
            kind="promoted",
            parent_hint="sessions/J0014010-calage",
        ),
        "identity": make_identity(),
        "checks": make_checks(),
        "tracked_inputs": [
            TrackedInput(
                role="dem",
                category="raster",
                path="data/dem/bdalti_25m.tif",
                declared_path="data/dem/bdalti_25m.tif",
                sha256="ab" * 32,
                bytes=1024,
                portable=True,
            )
        ],
        "inputs": [
            InputEntry(
                variable="discharge",
                provider="hubeau",
                product="hydrometrie",
                request={"stations": ["J0014010"], "period": ["2016-01-01", "2020-12-31"]},
                fetched_at=NOW,
                path="data/hydrometry/J0014010.parquet",
                sha256="cd" * 32,
                bytes=2048,
                license="etalab-2.0",
            )
        ],
        "parameters": [
            ParameterRow(
                name="K",
                value=6.1e-6,
                unit="m/s",
                parameterization="uniform",
                origin="calibrated",
                calibrated=True,
            ),
            ParameterRow(name="Sy", value=0.05, origin="declared", calibrated=False),
        ],
        "metrics": [
            MetricRow(
                station="J0014010",
                variable="discharge",
                metric="nse",
                value=0.81,
                nse_window_start=WINDOW.start,
                nse_window_end=WINDOW.end,
                nse_n=1827,
                metric_rule_version="1",
            )
        ],
        "score": MetricScore(
            metric="nse",
            value=0.81,
            nse_window_start=WINDOW.start,
            nse_window_end=WINDOW.end,
            nse_n=1827,
            metric_rule_version="1",
        ),
        "provenance": RunProvenance(
            sim_id=SIM_ID,
            tool={"name": "hydromodpy", "version": VERSION},
            platform={"platform": "Linux", "hostname": "node12", "user": "bb"},
            solver={"name": "modflow6", "binary_path": "/home/bb/.cache/hydromodpy/bin/mf6"},
            environment={"lock": "hydromodpy.lock", "binaries": {"mf6": "ef" * 32}},
        ),
    }
    payload.update(overrides)
    return RunRecord(**payload)
