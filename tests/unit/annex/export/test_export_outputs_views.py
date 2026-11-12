"""Tests of FAIR export views (STAC and PROV) moved to the annex."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pytest

from hydromodpy.core.exceptions import ExportError, SchemaVersionMismatchError
from hydromodpy.core.io.file_digest import sha256_and_size
from hydromodpy.results.export.context import FairExportContext
from hydromodpy.results.export.directory import context_from_directory
from hydromodpy.results.export.rocrate import write_ro_crate_view
from hydromodpy.results.record.manifest import list_artifacts
from hydromodpy.results.record.record import PROVENANCE_VERSION
from hydromodpy.results.storage.contract import ALLOWED_RUN_ENTRIES
from hydromodpy.results.zarr_store.constants import ZARR_SCHEMA_VERSION
from hydromodpy.schema.generated_views import (
    GENERATED_VIEWS,
    RO_CRATE_VIEW_FILENAME,
    STAC_ITEM_VIEW_FILENAME,
)
from hydromodpy.schema.job.directory import JobDirectory
from hydromodpy.schema.job.documents import read_document, write_document
from hydromodpy.schema.job.extent import SpatialExtent
from hydromodpy.schema.job.inputset import Licence, build_inputset, file_resource
from hydromodpy.schema.job.layout import ALLOWED_JOB_ENTRIES
from hydromodpy.schema.job.outcome import JobOutcome, OutputRecord
from hydromodpy.schema.job.seal import seal_job, verify_job
from hydromodpy.schema.media_types import GEOPACKAGE_MEDIA_TYPE, GEOTIFF_MEDIA_TYPE
from hydromodpy_annex.export.prov import write_prov_view
from hydromodpy_annex.export.stac import write_stac_item_view
from tests._helpers.sealed_runs import manifest_document

pytestmark = pytest.mark.fast

SIM_ID = "4b18da07-43bc-4b02-a7a8-41884e88f39e"
JOB_ID = "sha256:" + "7" * 64
SEALED_AT = "2026-09-11T00:40:16.903833+00:00"
NANCON_BBOX_L93 = [385087.5, 6814387.5, 396862.5, 6827287.5]


def write_views(
    directory: Path | str,
    formats: Iterable[str] = ("rocrate", "stac", "prov"),
) -> tuple[Path, ...]:
    """Write the requested views of a sealed directory inside it."""
    writers = {
        "rocrate": write_ro_crate_view,
        "stac": write_stac_item_view,
        "prov": write_prov_view,
    }
    requested = tuple(dict.fromkeys(formats))
    unknown = [name for name in requested if name not in writers]
    if unknown:
        raise ValueError(
            f"unknown view format(s) {', '.join(unknown)}; expected one of {', '.join(writers)}"
        )
    root = Path(directory)
    context = context_from_directory(root)
    return tuple(writers[name](root, context=context) for name in requested)


def _run_directory(
    root: Path, *, crs_epsg: int | None = 2154, bbox: list[float] | None = None
) -> Path:
    """A sealed run directory, written the way the run seal writes one."""
    run_dir = root / "runs" / "transient_nwt"
    (run_dir / "fields.zarr").mkdir(parents=True)
    (run_dir / "fields.zarr" / "zarr.json").write_text(
        json.dumps({"attributes": {"zarr_schema_version": ZARR_SCHEMA_VERSION}}), encoding="utf-8"
    )
    (run_dir / "tables.parquet").mkdir()
    (run_dir / "tables.parquet" / "mass_balance.parquet").write_bytes(b"PAR1" * 8)
    (run_dir / "config.toml").write_text("[simulation]\n", encoding="utf-8")
    (run_dir / "provenance.json").write_text(
        json.dumps(
            {
                "provenance_version": PROVENANCE_VERSION,
                "sim_id": SIM_ID,
                "tool": {"name": "hydromodpy", "version": "2.0.0a1"},
                "git": {"commit": "c2fd549bd950e321ddbd04505ad9a5cea516ecd0", "dirty": True},
                "platform": {"hostname": "workstation", "user": "someone"},
                "environment": {"rng_seed": 7},
                "solver": {
                    "name": "modflow_nwt",
                    "version": "1.3.0",
                    "binary_sha256": "ab" * 32,
                },
            }
        ),
        encoding="utf-8",
    )
    manifest = manifest_document(
        sim_id=SIM_ID,
        name="transient_nwt",
        sealed_at=SEALED_AT,
        run={
            "project": "02_nancon_watershed",
            "solver": "modflow_nwt",
            "started_at": "2026-09-11T02:40:15+02:00",
            "ended_at": "2026-09-11T02:40:16+02:00",
            "description": "Nancon, transient, MODFLOW-NWT.",
        },
        geometry={
            "n_cells": 27004,
            "n_layers": 1,
            "crs_wkt": "EPSG:2154",
            "crs_epsg": crs_epsg,
            "bbox": NANCON_BBOX_L93 if bbox is None else bbox,
        },
        period={
            "start": "2000-01-01T00:00:00+01:00",
            "end": "2003-01-01T00:00:00+01:00",
            "n_timesteps": 36,
        },
        inputs=[
            {
                "role": "dem",
                "category": "data",
                "declared_path": "DEM_armorican_massif.tif",
                "path": str(root / "private" / "home" / "DEM_armorican_massif.tif"),
                "portable": False,
                "sha256": "e2" * 32,
                "bytes": 94812848,
            }
        ],
        artifacts=list_artifacts(run_dir),
    )
    (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return run_dir


def _job_directory(
    root: Path,
    *,
    spatial: SpatialExtent | None = None,
    geometry: SpatialExtent | None = None,
) -> JobDirectory:
    """A sealed job directory, written through the job package itself."""
    job = JobDirectory.create(root / "job_4711")
    job.ensure_workspace()
    job.request_path.write_text("{}", encoding="utf-8")
    dem = root / "dem.tif"
    dem.write_bytes(b"II*\x00" * 64)
    inputset = build_inputset(
        [
            file_resource(
                "dem",
                role="dem",
                path=dem,
                media_type=GEOTIFF_MEDIA_TYPE,
                licence=Licence(spdx="etalab-2.0", confidence="assumed"),
                spatial=spatial,
            )
        ]
    )
    produced = job.outputs_dir / "watershed.gpkg"
    produced.write_bytes(b"SQLite format 3\x00")
    digest, size = sha256_and_size(produced)
    outputs = (
        OutputRecord(
            id="watershed_vector",
            path="outputs/watershed.gpkg",
            media_type=GEOPACKAGE_MEDIA_TYPE,
            bytes=size,
            sha256=digest,
        ),
    )
    write_document(job.inputset_path, inputset.to_document())
    write_document(
        job.provenance_path,
        {
            "schema": "hmp-provenance/v1",
            "job_id": JOB_ID,
            "process": {"id": "domain-build", "version": "1.0.0"},
            "tool": {"name": "hydromodpy", "version": "2.0.0a1"},
            "git": {"commit": None, "dirty": None},
            "backend": {"name": "whitebox", "version": "2.4.0", "sha256": "cd" * 32},
        },
    )
    JobOutcome(
        job_id=JOB_ID,
        process_id="domain-build",
        process_version="1.0.0",
        status="successful",
        exit_code=0,
        started_at="2026-09-16T08:12:05.113Z",
        finished_at="2026-09-16T08:14:41.882Z",
        outputs=outputs,
    ).write(job)
    seal_job(job, job_id=JOB_ID, inputset=inputset, outputs=outputs, geometry=geometry)
    return job


def _rewrite_dem_spatial(job: JobDirectory, spatial: Any) -> None:
    """Put another extent document on the DEM resource of a sealed job."""
    inputset = dict(read_document(job.inputset_path))
    inputset["resources"] = [
        {**resource, "spatial": spatial} if resource["name"] == "dem" else resource
        for resource in inputset["resources"]
    ]
    write_document(job.inputset_path, inputset)


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


class TestARunDirectory:
    def test_the_views_stay_out_of_the_seal_and_inside_the_layout(self, tmp_path: Path) -> None:
        run_dir = _run_directory(tmp_path)
        write_views(run_dir)
        inventoried = {entry["path"] for entry in list_artifacts(run_dir)}
        assert not inventoried & GENERATED_VIEWS
        assert {entry.name for entry in run_dir.iterdir()} <= ALLOWED_RUN_ENTRIES


class TestAJobDirectory:
    @pytest.mark.parametrize(
        "document", ["manifest.json", "inputset.json", "provenance.json", "outcome.json"]
    )
    def test_a_document_of_a_later_version_is_refused_by_name(
        self, document: str, tmp_path: Path
    ) -> None:
        job = _job_directory(tmp_path)
        target = job.root / document
        payload = _read(target)
        if "manifest_version" in payload:
            payload["manifest_version"] = 9
        else:
            payload["schema"] = re.sub(r"\d+$", "9", payload["schema"])
        target.write_text(json.dumps(payload), encoding="utf-8")

        with pytest.raises(SchemaVersionMismatchError, match=document):
            write_views(job.root)

    def test_the_views_land_inside_the_job_and_leave_the_seal_intact(self, tmp_path: Path) -> None:
        job = _job_directory(tmp_path)
        manifest_before = job.manifest_path.read_bytes()
        written = write_views(job.root)
        assert {path.parent for path in written} == {job.root}
        assert job.manifest_path.read_bytes() == manifest_before
        assert verify_job(job).ok
        assert {entry.name for entry in job.root.iterdir()} <= ALLOWED_JOB_ENTRIES

    def test_the_extent_a_worker_measured_is_reprojected_to_wgs84(self, tmp_path: Path) -> None:
        spatial = SpatialExtent(bbox=NANCON_BBOX_L93, crs="EPSG:2154")
        job = _job_directory(tmp_path, spatial=spatial)
        write_views(job.root)
        item = _read(job.root / STAC_ITEM_VIEW_FILENAME)
        xmin, ymin, xmax, ymax = item["bbox"]
        assert -1.4 < xmin < xmax < -1.0
        assert 48.2 < ymin < ymax < 48.6
        assert item["geometry"]["type"] == "Polygon"
        assert item["properties"]["proj:epsg"] == 2154
        crate = _read(job.root / RO_CRATE_VIEW_FILENAME)
        boxes = [node["box"] for node in crate["@graph"] if node.get("@type") == "GeoShape"]
        assert len(boxes) == 1
        assert boxes[0].split() == [str(v) for v in (ymin, xmin, ymax, xmax)]

    def test_an_extent_measured_in_wgs84_is_kept_as_measured(self, tmp_path: Path) -> None:
        box = [-1.2620, 48.3530, -1.0940, 48.4750]
        job = _job_directory(tmp_path, spatial=SpatialExtent(bbox=box, crs="EPSG:4326"))
        item = _read(write_stac_item_view(job.root))
        assert item["bbox"] == pytest.approx(box)
        assert item["properties"]["proj:epsg"] == 4326

    def test_a_job_that_records_no_extent_gives_no_box(self, tmp_path: Path) -> None:
        job = _job_directory(tmp_path)
        item = _read(write_stac_item_view(job.root))
        assert "bbox" not in item
        assert item["geometry"] is None

    def test_the_extent_the_seal_records_is_the_one_the_view_publishes(
        self, tmp_path: Path
    ) -> None:
        box = [-1.2620, 48.3530, -1.0940, 48.4750]
        job = _job_directory(
            tmp_path,
            spatial=SpatialExtent(bbox=NANCON_BBOX_L93, crs="EPSG:2154"),
            geometry=SpatialExtent(bbox=box, crs="EPSG:4326"),
        )
        assert _read(job.manifest_path)["geometry"] == {"crs": "EPSG:4326", "bbox": box}
        item = _read(write_stac_item_view(job.root))
        assert item["bbox"] == pytest.approx(box)
        assert item["properties"]["proj:epsg"] == 4326

    @pytest.mark.parametrize(
        "spatial",
        [
            {"crs": "EPSG:2154", "bbox_wgs84": [-1.2620, 48.3530, -1.0940, 48.4750]},
            {"bbox": NANCON_BBOX_L93},
            {"crs": "EPSG:2154"},
            {"crs": "EPSG:2154", "bbox": NANCON_BBOX_L93, "bbox_wgs84": [-1.3, 48.3, -1.1, 48.5]},
            {"crs": "lambert93", "bbox": NANCON_BBOX_L93},
        ],
        ids=["wgs84-spelling", "no-crs", "no-bbox", "second-box", "unparsed-crs"],
    )
    def test_an_extent_in_another_shape_is_refused_not_skipped(
        self, tmp_path: Path, spatial: dict[str, Any]
    ) -> None:
        job = _job_directory(tmp_path)
        _rewrite_dem_spatial(job, spatial)
        with pytest.raises(ExportError, match="resource 'dem' is not a spatial extent"):
            write_views(job.root)
        assert not (job.root / STAC_ITEM_VIEW_FILENAME).exists()

    def test_a_seal_geometry_in_the_wkt2_spelling_is_refused(self, tmp_path: Path) -> None:
        job = _job_directory(tmp_path)
        manifest = dict(read_document(job.manifest_path))
        manifest["geometry"] = {
            "crs": "EPSG:2154",
            "crs_wkt2": "PROJCRS[...]",
            "bbox_wgs84": [-1.2620, 48.3530, -1.0940, 48.4750],
        }
        write_document(job.manifest_path, manifest)
        with pytest.raises(ExportError, match="geometry is not a spatial extent"):
            context_from_directory(job.root)


class TestWhatIsRefused:
    def test_an_unsealed_directory_renders_nothing(self, tmp_path: Path) -> None:
        job = JobDirectory.create(tmp_path / "job_unsealed")
        job.ensure_workspace()
        with pytest.raises(ExportError, match="not sealed"):
            write_views(job.root)
        assert not {entry.name for entry in job.root.iterdir()} & GENERATED_VIEWS

    def test_a_manifest_of_no_known_profile_is_refused(self, tmp_path: Path) -> None:
        (tmp_path / "manifest.json").write_text('{"schema": "other"}', encoding="utf-8")
        with pytest.raises(ExportError, match="neither a run manifest nor a job manifest"):
            context_from_directory(tmp_path)
