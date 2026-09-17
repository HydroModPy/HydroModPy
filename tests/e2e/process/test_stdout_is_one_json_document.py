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


def test_a_directory_a_transfer_truncated_is_reported_and_not_refused(tmp_path, finished):
    """The file a transfer drops first is ``request.json``, which verify does not need."""
    source, _ = finished
    import shutil

    job = tmp_path / "truncated"
    shutil.copytree(source, job)
    (job / "request.json").unlink()

    completed = _hmp("process", "verify", "--job", str(job), "--format", "json")

    assert completed.returncode == 0, completed.stderr[-4000:]
    assert json.loads(completed.stdout) == {"sealed": True, "ok": True, "problems": []}


def test_verify_reports_an_unsealed_directory_instead_of_crashing(tmp_path):
    bare = tmp_path / "bare"
    bare.mkdir()

    completed = _hmp("process", "verify", "--job", str(bare), "--format", "json")

    assert completed.returncode == EXIT_VALIDATION
    report = json.loads(completed.stdout)
    assert report == {"sealed": False, "ok": False, "problems": ["manifest.json is absent"]}
    assert "Traceback" not in completed.stderr


def test_the_signal_handler_is_installed_before_the_parser_is_built():
    """Building the parser imports every command module, seconds of real work.

    A handler installed after it missed the window it was written for: a
    SIGTERM arriving while ``hmp`` was still assembling its own argparse tree
    killed the process where it stood, and a job about to start left no trace
    at all. So the handler goes on first, for every verb.
    """
    # importlib, not ``import hydromodpy.cli.main as m``: the package exports a
    # function under that name, which shadows its own submodule.
    script = (
        "import importlib, signal, sys\n"
        "m = importlib.import_module('hydromodpy.cli.main')\n"
        "real = m._build_parser\n"
        "seen = {}\n"
        "def spy():\n"
        "    seen['handler'] = signal.getsignal(signal.SIGTERM)\n"
        "    return real()\n"
        "m._build_parser = spy\n"
        "try:\n"
        "    m.main(['process', 'list'])\n"
        "except SystemExit:\n"
        "    pass\n"
        "sys.exit(0 if seen.get('handler') not in (signal.SIG_DFL, None) else 9)\n"
    )

    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )

    assert completed.returncode == 0, (
        f"SIGTERM was still the default while the parser was built: {completed.stderr[-2000:]}"
    )


def test_a_sigterm_before_the_run_starts_seals_nothing_and_says_nothing(tmp_path):
    """The window no Python code can close, asserted for what it really gives.

    A signal that lands before the interpreter has run a line of HydroModPy
    ends the process where it stands. That is not a defect of this verb and
    no handler can change it. What must hold anyway is the invariant a caller
    outside the process relies on: the seal is absent, and stdout carries
    either one whole document or nothing, never half of one.
    """
    import signal as signal_module

    job = _job(tmp_path, _request())
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "hydromodpy",
            "process",
            "run",
            "terrain-delineate",
            "--job",
            str(job),
        ],
        cwd=str(REPO_ROOT),
        env=dict(os.environ, HMP_NO_PROGRESS="1"),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    process.send_signal(signal_module.SIGTERM)
    stdout, _ = process.communicate(timeout=300)

    assert not (job / "manifest.json").exists()
    assert stdout == "" or json.loads(stdout)["status"] in ("dismissed", "failed")


def test_a_sigterm_once_the_body_is_running_writes_a_dismissed_outcome(tmp_path):
    """The full promise of §1.8, on a run that has provably started.

    Keyed on ``outputs/`` appearing rather than on a delay: that directory is
    created by the capability body itself, so once it is there the signal
    cannot land anywhere but inside the work.
    """
    import signal as signal_module
    import time

    job = _job(tmp_path, _request())
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "hydromodpy",
            "process",
            "run",
            "terrain-delineate",
            "--job",
            str(job),
        ],
        cwd=str(REPO_ROOT),
        env=dict(os.environ, HMP_NO_PROGRESS="1"),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    deadline = time.monotonic() + 120.0
    while not (job / "outputs").is_dir() and process.poll() is None:
        if time.monotonic() > deadline:
            process.kill()
            pytest.fail("the capability never created outputs/")
        time.sleep(0.01)
    if process.poll() is not None:
        process.communicate(timeout=60)
        pytest.skip("the job finished before the signal could be sent")
    process.send_signal(signal_module.SIGTERM)
    stdout, stderr = process.communicate(timeout=300)

    assert process.returncode == 130, f"exit {process.returncode}; stderr: {stderr[-2000:]}"
    assert not (job / "manifest.json").exists()
    outcome = json.loads((job / "outcome.json").read_text(encoding="utf-8"))
    assert outcome["status"] == "dismissed"
    assert outcome["exit_code"] == 130
    assert stdout == (job / "outcome.json").read_text(encoding="utf-8")


def test_a_sigterm_after_the_outcome_is_written_does_not_rewrite_the_exit_code():
    """A signal landing after the job finished must not contradict the document.

    ``terminate_as_interrupt`` restores the previous handler when its block
    ends, which left a window between "the outcome is sealed" and "the process
    exits with its code". A SIGTERM there killed a successful job at 143, so
    the shell read a failure while the document said ``successful`` and 0.
    """
    script = (
        "import os, signal, sys, time\n"
        "from hydromodpy.cli.commands.process.run_job import ignore_termination\n"
        "ignore_termination()\n"
        "os.kill(os.getpid(), signal.SIGTERM)\n"
        "time.sleep(0.3)\n"
        "sys.exit(7)\n"
    )

    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )

    assert completed.returncode == 7, "SIGTERM still reached a process that had already decided"


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
