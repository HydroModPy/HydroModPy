"""A sealed run or job directory renders its FAIR views by itself, inside itself.

The three exporters used to need the catalog, and wrote under ``share/``,
outside the directory the contract calls the run. These tests build each
profile by hand, with no workspace and no index, and check that the views
land beside the seal, resolve against it, and say only what it says.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import hydromodpy.results.export.context as context_module
import hydromodpy.results.export.prov as prov_module
import hydromodpy.results.export.rocrate as rocrate_module
import hydromodpy.results.export.stac as stac_module
from hydromodpy.core.exceptions import ExportError
from hydromodpy.results.export import (
    context_from_directory,
    write_prov_view,
    write_ro_crate_view,
    write_stac_item_view,
    write_views,
)
from hydromodpy.results.export.stac import validate_item
from hydromodpy.results.manifest import list_artifacts
from hydromodpy.results.storage.contract import ALLOWED_RUN_ENTRIES
from hydromodpy.schema.generated_views import (
    GENERATED_VIEWS,
    PROV_VIEW_FILENAME,
    RO_CRATE_VIEW_FILENAME,
    STAC_ITEM_VIEW_FILENAME,
)
from hydromodpy.schema.job.digest import sha256_file
from hydromodpy.schema.job.directory import JobDirectory
from hydromodpy.schema.job.documents import read_document, write_document
from hydromodpy.schema.job.extent import SpatialExtent
from hydromodpy.schema.job.inputset import Licence, build_inputset, file_resource
from hydromodpy.schema.job.layout import ALLOWED_JOB_ENTRIES
from hydromodpy.schema.job.outcome import JobOutcome, OutputRecord
from hydromodpy.schema.job.seal import seal_job, verify_job
from hydromodpy.schema.media_types import GEOPACKAGE_MEDIA_TYPE, GEOTIFF_MEDIA_TYPE

pytestmark = pytest.mark.fast

SIM_ID = "4b18da07-43bc-4b02-a7a8-41884e88f39e"
JOB_ID = "sha256:" + "7" * 64
SEALED_AT = "2026-09-11T00:40:16.903833+00:00"
# The Nancon catchment in Lambert-93, as a real run seal records it.
NANCON_BBOX_L93 = [385087.5, 6814387.5, 396862.5, 6827287.5]


@pytest.fixture(autouse=True)
def _no_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail loudly if any view reaches for the catalog constructor."""

    def _refuse(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("a directory view must not build a catalog context")

    for module in (context_module, prov_module, rocrate_module, stac_module):
        monkeypatch.setattr(module, "build_context", _refuse)


def _run_directory(
    root: Path, *, crs_epsg: int | None = 2154, bbox: list[float] | None = None
) -> Path:
    """A sealed run directory, written the way the run seal writes one."""
    run_dir = root / "runs" / "transient_nwt"
    (run_dir / "fields.zarr").mkdir(parents=True)
    (run_dir / "fields.zarr" / "zarr.json").write_text("{}", encoding="utf-8")
    (run_dir / "tables.parquet").mkdir()
    (run_dir / "tables.parquet" / "mass_balance.parquet").write_bytes(b"PAR1" * 8)
    (run_dir / "config.toml").write_text("[simulation]\n", encoding="utf-8")
    (run_dir / "provenance.json").write_text(
        json.dumps(
            {
                "provenance_version": 1,
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
    manifest = {
        "manifest_version": 1,
        "sealed_at": SEALED_AT,
        "run": {
            "sim_id": SIM_ID,
            "name": "transient_nwt",
            "project": "02_nancon_watershed",
            "solver": "modflow_nwt",
            "started_at": "2026-09-11T02:40:15+02:00",
            "ended_at": "2026-09-11T02:40:16+02:00",
            "description": "Nancon, transient, MODFLOW-NWT.",
            "contact_email": None,
            "doi": None,
        },
        "geometry": {
            "n_cells": 27004,
            "n_layers": 1,
            "crs_wkt": "EPSG:2154",
            "crs_epsg": crs_epsg,
            "bbox": NANCON_BBOX_L93 if bbox is None else bbox,
        },
        "period": {
            "start": "2000-01-01T00:00:00+01:00",
            "end": "2003-01-01T00:00:00+01:00",
            "n_timesteps": 36,
        },
        "inputs": [
            {
                "role": "dem",
                "category": "data",
                "path": str(root / "private" / "home" / "DEM_armorican_massif.tif"),
                "sha256": "e2" * 32,
                "bytes": 94812848,
            }
        ],
        "artifacts": list_artifacts(run_dir),
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return run_dir


def _job_directory(
    root: Path,
    *,
    spatial: SpatialExtent | None = None,
    geometry: SpatialExtent | None = None,
) -> JobDirectory:
    """A sealed job directory, written through the job package itself.

    *spatial* is the extent recorded on the DEM resource, *geometry* the one
    the seal records. Both are a native ``bbox`` and the ``crs`` it is in.
    """
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
    digest, size = sha256_file(produced)
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
            "process": {"id": "terrain-delineate", "version": "1.0.0"},
            "tool": {"name": "hydromodpy", "version": "2.0.0a1"},
            "git": {"commit": None, "dirty": None},
            "backend": {"name": "whitebox", "version": "2.4.0", "sha256": "cd" * 32},
        },
    )
    JobOutcome(
        job_id=JOB_ID,
        process_id="terrain-delineate",
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
    """Put another extent document on the DEM resource of a sealed job.

    The view does not verify the seal, so this reaches the reader as a
    producer that wrote this shape would have left it.
    """
    inputset = dict(read_document(job.inputset_path))
    inputset["resources"] = [
        {**resource, "spatial": spatial} if resource["name"] == "dem" else resource
        for resource in inputset["resources"]
    ]
    write_document(job.inputset_path, inputset)


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


class TestARunDirectory:
    def test_the_three_views_land_beside_the_seal(self, tmp_path: Path) -> None:
        run_dir = _run_directory(tmp_path)
        written = write_views(run_dir)
        assert {path.name for path in written} == set(GENERATED_VIEWS)
        assert all(path.parent == run_dir for path in written)
        assert not (tmp_path / "share").exists()

    def test_every_asset_href_resolves_inside_the_directory(self, tmp_path: Path) -> None:
        run_dir = _run_directory(tmp_path)
        item = _read(write_stac_item_view(run_dir))
        hrefs = {asset["href"] for asset in item["assets"].values()}
        assert {"manifest.json", "config.toml", "fields.zarr"} <= hrefs
        assert "tables.parquet/mass_balance.parquet" in hrefs
        assert all((run_dir / href).exists() for href in hrefs)

    def test_the_stac_item_is_valid_standalone_and_in_wgs84(self, tmp_path: Path) -> None:
        pytest.importorskip("pystac")
        item = _read(write_stac_item_view(_run_directory(tmp_path)))
        ok, errors = validate_item(item)
        assert ok, errors
        assert "collection" not in item
        assert item["links"] == [
            {"rel": "self", "href": STAC_ITEM_VIEW_FILENAME, "type": "application/geo+json"}
        ]
        xmin, ymin, xmax, ymax = item["bbox"]
        # Lambert-93 metres reprojected onto the Rennes basin, in degrees.
        assert -1.4 < xmin < xmax < -1.0
        assert 48.2 < ymin < ymax < 48.6
        assert item["properties"]["proj:epsg"] == 2154
        # The seal spells an EPSG code in crs_wkt; the view does not call it WKT2.
        assert "proj:wkt2" not in item["properties"]

    def test_a_box_whose_crs_is_unknown_is_left_out(self, tmp_path: Path) -> None:
        run_dir = _run_directory(tmp_path, crs_epsg=None, bbox=[0.0, 0.0, 400.0, 50.0])
        item = _read(write_stac_item_view(run_dir))
        assert "bbox" not in item
        assert item["geometry"] is None

    def test_a_licence_nobody_chose_is_not_invented(self, tmp_path: Path) -> None:
        run_dir = _run_directory(tmp_path)
        write_views(run_dir)
        crate = _read(run_dir / RO_CRATE_VIEW_FILENAME)
        root = next(node for node in crate["@graph"] if node["@id"] == "./")
        assert root["license"] == {"@id": "LicenseRef-undetermined"}
        item = _read(run_dir / STAC_ITEM_VIEW_FILENAME)
        assert item["properties"]["license"] == "LicenseRef-undetermined"
        for name in GENERATED_VIEWS:
            assert "CC-BY-4.0" not in (run_dir / name).read_text(encoding="utf-8")

    def test_a_view_names_no_local_path_and_no_account(self, tmp_path: Path) -> None:
        run_dir = _run_directory(tmp_path)
        for path in write_views(run_dir):
            text = path.read_text(encoding="utf-8")
            assert str(tmp_path) not in text
            assert "workstation" not in text
            assert "someone" not in text

    def test_rendering_twice_gives_the_same_bytes(self, tmp_path: Path) -> None:
        run_dir = _run_directory(tmp_path)
        first = [path.read_bytes() for path in write_views(run_dir)]
        second = [path.read_bytes() for path in write_views(run_dir)]
        assert first == second
        crate = _read(run_dir / RO_CRATE_VIEW_FILENAME)
        root = next(node for node in crate["@graph"] if node["@id"] == "./")
        assert root["datePublished"] == SEALED_AT

    def test_the_crate_loads_in_the_reference_library(self, tmp_path: Path) -> None:
        pytest.importorskip("rocrate")
        from rocrate.rocrate import ROCrate

        run_dir = _run_directory(tmp_path)
        write_ro_crate_view(run_dir)
        crate = ROCrate(run_dir)
        assert str(crate.root_dataset.id) == "./"
        parts = {str(part["@id"]) for part in crate.root_dataset.properties()["hasPart"]}
        assert "manifest.json" in parts
        assert all((run_dir / part).exists() for part in parts)

    def test_the_lineage_links_every_output_to_the_input(self, tmp_path: Path) -> None:
        run_dir = _run_directory(tmp_path)
        graph = _read(write_prov_view(run_dir))["@graph"]
        action = graph[0]
        assert action["hydromodpy:gitCommit"] == "c2fd549bd950e321ddbd04505ad9a5cea516ecd0"
        assert action["hydromodpy:rngSeed"] == 7
        inputs = [node for node in graph if node["@id"].startswith("#entity/input/")]
        assert [node["name"] for node in inputs] == ["DEM_armorican_massif.tif"]
        outputs = [node for node in graph if node["@id"].startswith("#entity/output/")]
        assert outputs
        assert all(node["prov:wasDerivedFrom"] == [{"@id": inputs[0]["@id"]}] for node in outputs)

    def test_the_views_stay_out_of_the_seal_and_inside_the_layout(self, tmp_path: Path) -> None:
        run_dir = _run_directory(tmp_path)
        write_views(run_dir)
        inventoried = {entry["path"] for entry in list_artifacts(run_dir)}
        assert not inventoried & GENERATED_VIEWS
        assert {entry.name for entry in run_dir.iterdir()} <= ALLOWED_RUN_ENTRIES


class TestAJobDirectory:
    def test_the_views_land_inside_the_job_and_leave_the_seal_intact(self, tmp_path: Path) -> None:
        job = _job_directory(tmp_path)
        manifest_before = job.manifest_path.read_bytes()
        written = write_views(job.root)
        assert {path.parent for path in written} == {job.root}
        assert job.manifest_path.read_bytes() == manifest_before
        assert verify_job(job).ok
        assert {entry.name for entry in job.root.iterdir()} <= ALLOWED_JOB_ENTRIES

    def test_the_views_carry_the_digests_the_seal_recorded(self, tmp_path: Path) -> None:
        pytest.importorskip("pystac")
        job = _job_directory(tmp_path)
        item = _read(write_stac_item_view(job.root))
        assert validate_item(item) == (True, [])
        assert item["id"] == JOB_ID
        sealed = {entry["path"]: entry for entry in _read(job.manifest_path)["artifacts"]}
        gpkg = item["assets"]["outputs/watershed.gpkg"]
        assert gpkg["type"] == GEOPACKAGE_MEDIA_TYPE
        assert gpkg["roles"] == ["data"]
        assert gpkg["file:checksum"] == "1220" + sealed["outputs/watershed.gpkg"]["sha256"]

    def test_the_extent_a_worker_measured_is_reprojected_to_wgs84(self, tmp_path: Path) -> None:
        # data/fetch/worker.py records the mask extent in its own CRS.
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

    def test_the_licence_is_the_rollup_of_the_input_set(self, tmp_path: Path) -> None:
        job = _job_directory(tmp_path)
        write_views(job.root)
        item = _read(job.root / STAC_ITEM_VIEW_FILENAME)
        assert item["properties"]["license"] == "etalab-2.0"
        crate = _read(job.root / RO_CRATE_VIEW_FILENAME)
        root = next(node for node in crate["@graph"] if node["@id"] == "./")
        assert root["license"] == {"@id": "https://spdx.org/licenses/etalab-2.0"}
        dem = next(node for node in crate["@graph"] if node.get("hydromodpy:role") == "dem")
        assert dem["license"] == "etalab-2.0"

    def test_the_backend_is_the_solver_agent(self, tmp_path: Path) -> None:
        job = _job_directory(tmp_path)
        context = context_from_directory(job.root)
        assert context.solver_name == "whitebox"
        assert context.solver_binary_sha256 == "cd" * 32
        assert context.sim_row["name"] == "terrain-delineate 1.0.0"
        graph = _read(write_prov_view(job.root))["@graph"]
        assert graph[0]["startTime"] == "2026-09-16T08:12:05.113Z"

    def test_a_job_view_is_dated_by_its_seal(self, tmp_path: Path) -> None:
        job = _job_directory(tmp_path)
        sealed_at = _read(job.manifest_path)["sealed_at"]
        item = _read(write_stac_item_view(job.root))
        crate = _read(write_ro_crate_view(job.root))
        root = next(node for node in crate["@graph"] if node["@id"] == "./")
        assert root["datePublished"] == sealed_at
        assert item["properties"]["datetime"].startswith(sealed_at[:16])


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

    def test_an_unknown_format_is_refused_before_anything_is_written(self, tmp_path: Path) -> None:
        run_dir = _run_directory(tmp_path)
        with pytest.raises(ValueError, match="datapackage"):
            write_views(run_dir, ("stac", "datapackage"))
        assert not (run_dir / STAC_ITEM_VIEW_FILENAME).exists()
        assert not (run_dir / PROV_VIEW_FILENAME).exists()
