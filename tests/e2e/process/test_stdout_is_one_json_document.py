"""``hmp process run`` through a real pipe, which is the only honest test of it.

The promise of this verb is about bytes on a file descriptor: a caller that
captured the pipe and a caller that opens the job directory must learn the
same thing. Asserting that in process, by calling the worker, proves nothing
about what a banner or a progress renderer writes on the way out. So every
test here spawns a subprocess and reads its two streams.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("whitebox_workflows")

REPO_ROOT = Path(__file__).resolve().parents[3]
DEM = REPO_ROOT / "tests" / "data" / "sfr_cheze" / "dem_valley.tif"
OUTLET_X = 300112.5
OUTLET_Y = 6701262.5

EXIT_USAGE = 2
EXIT_CONFIG = 14
EXIT_VALIDATION = 16


def _request(**inputs: object) -> dict:
    payload: dict[str, object] = {
        "dem": {"href": str(DEM), "type": "image/tiff; application=geotiff"},
        "outlets": [{"site_id": "valley", "x": OUTLET_X, "y": OUTLET_Y}],
        "crs_project": "EPSG:2154",
        "dem_correction_type": "breach",
        "snap_distance_m": 100,
    }
    payload.update(inputs)
    return {"process": {"id": "terrain-delineate", "version": "1.0.0"}, "inputs": payload}


def _job(tmp_path: Path, document: dict, *, name: str = "job") -> Path:
    root = tmp_path / name
    root.mkdir(parents=True)
    (root / "request.json").write_text(json.dumps(document), encoding="utf-8")
    return root


def _hmp(*argv: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "hydromodpy", *argv],
        cwd=str(REPO_ROOT),
        env=dict(os.environ, HMP_NO_PROGRESS="1"),
        capture_output=True,
        text=True,
        timeout=900,
        check=False,
    )


@pytest.fixture(scope="module")
def finished(tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("process_run")
    job = _job(tmp_path, _request())
    completed = _hmp("process", "run", "terrain-delineate", "--job", str(job))
    return job, completed


def test_stdout_is_one_json_document_and_nothing_else(finished):
    job, completed = finished

    assert completed.returncode == 0, completed.stderr[-4000:]
    document = json.loads(completed.stdout)
    assert document["status"] == "successful"
    assert document["process"]["id"] == "terrain-delineate"


def test_stdout_is_byte_identical_to_the_outcome_on_disk(finished):
    job, completed = finished

    assert completed.stdout == (job / "outcome.json").read_text(encoding="utf-8")


def test_the_job_is_sealed_and_the_verify_verb_says_so(finished):
    job, _ = finished

    completed = _hmp("process", "verify", "--job", str(job), "--format", "json")

    assert completed.returncode == 0, completed.stderr[-4000:]
    assert json.loads(completed.stdout) == {"sealed": True, "ok": True, "problems": []}


def test_a_tampered_artefact_makes_verify_exit_on_validation(tmp_path, finished):
    source, _ = finished
    import shutil

    job = tmp_path / "tampered"
    shutil.copytree(source, job)
    raster = job / "outputs" / "flow_direction.tif"
    raster.write_bytes(raster.read_bytes() + b"\x00")

    completed = _hmp("process", "verify", "--job", str(job), "--format", "json")

    assert completed.returncode == EXIT_VALIDATION
    report = json.loads(completed.stdout)
    assert report["ok"] is False
    assert any("flow_direction.tif" in problem for problem in report["problems"])


def test_the_listing_names_the_capability_this_build_serves():
    completed = _hmp("process", "list", "--format", "json")

    assert completed.returncode == 0, completed.stderr[-4000:]
    served = {record["id"]: record for record in json.loads(completed.stdout)}
    assert "terrain-delineate" in served
    assert served["terrain-delineate"]["major"] == 1


def test_a_capability_nobody_serves_is_a_usage_error(tmp_path):
    job = _job(tmp_path, _request())

    completed = _hmp("process", "run", "data-fetch", "--job", str(job))

    assert completed.returncode == EXIT_USAGE
    assert completed.stdout == ""
    assert "data-fetch" in completed.stderr


def test_a_directory_without_a_request_is_a_usage_error(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()

    completed = _hmp("process", "run", "terrain-delineate", "--job", str(empty))

    assert completed.returncode == EXIT_USAGE
    assert completed.stdout == ""
    assert "request.json" in completed.stderr


def test_a_refused_document_still_puts_its_outcome_on_stdout(tmp_path):
    """Exit 14, and the problem object on stdout rather than a traceback."""
    job = _job(tmp_path, _request(crs_project="lambert93"))

    completed = _hmp("process", "run", "terrain-delineate", "--job", str(job))

    assert completed.returncode == EXIT_CONFIG
    document = json.loads(completed.stdout)
    assert document["status"] == "failed"
    assert document["errors"][0]["code"] == "HMPY.E101"
    assert document["errors"][0]["details"][0]["pointer"] == "/inputs/crs_project"
    assert not (job / "manifest.json").exists()


def test_a_stranger_opens_the_sealed_directory_with_plain_readers(finished):
    """GDAL, pandas and json, with nothing of HydroModPy imported."""
    job, _ = finished
    script = (
        "import json, sys\n"
        "import geopandas as gpd\n"
        "import rasterio\n"
        "root = sys.argv[1]\n"
        "frame = gpd.read_file(root + '/outputs/watershed.gpkg')\n"
        "table = gpd.read_parquet(root + '/outputs/watershed.parquet')\n"
        "points = json.loads(open(root + '/outputs/outlets_snapped.geojson').read())\n"
        "with rasterio.open(root + '/outputs/flow_direction.tif') as src:\n"
        "    bands = src.count\n"
        "seal = json.loads(open(root + '/manifest.json').read())\n"
        "print(json.dumps({'rows': len(frame), 'cols': len(table.columns),\n"
        "                  'features': len(points['features']), 'bands': bands,\n"
        "                  'artifacts': len(seal['artifacts'])}))\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", script, str(job)],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr[-4000:]
    read = json.loads(completed.stdout)
    assert read == {"rows": 1, "cols": 8, "features": 1, "bands": 1, "artifacts": 9}
