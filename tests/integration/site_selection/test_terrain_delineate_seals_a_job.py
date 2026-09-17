"""``terrain-delineate`` invoked the way an orchestrator invokes it.

One directory in, one seal out. These tests read the directory the way a
stranger would: with ``geopandas`` and ``json``, never through the objects
that wrote it, because what the boundary promises is that a third party can
do exactly that.

The DEM is ``tests/data/sfr_cheze/dem_valley.tif``: 100 x 100 cells of 25 m in
EPSG:2154, a valley draining west to (300012.5, 6701262.5). The outlet is
declared 100 m east of the talweg so the snap has something to do.
"""

from __future__ import annotations

import ipaddress
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from hydromodpy.cli.helpers import (
    EXIT_CONFIG,
    EXIT_NOT_FOUND,
    EXIT_SOLVER_ERROR,
    EXIT_VALIDATION,
    exit_code_for,
)
from hydromodpy.core.exceptions import DataContractViolation, JobUsageError
from hydromodpy.schema.job import UNIDENTIFIED_JOB, JobDirectory, read_document, verify_job
from hydromodpy.schema.job.digest import sha256_file
from hydromodpy.schema.job.layout import ALLOWED_JOB_ENTRIES
from hydromodpy.spatial.site_selection.hydrology.capability import TERRAIN_DELINEATE
from hydromodpy.spatial.site_selection.hydrology.worker import run

gpd = pytest.importorskip("geopandas")
pytest.importorskip("whitebox_workflows")

# Whitebox's native binding is not fork-safe under xdist distribution.
pytestmark = pytest.mark.xdist_group(name="whitebox_backend")

DEM = Path(__file__).resolve().parents[3] / "tests" / "data" / "sfr_cheze" / "dem_valley.tif"
OUTLET_X = 300112.5
OUTLET_Y = 6701262.5


def _request(**overrides: object) -> dict:
    inputs: dict[str, object] = {
        "dem": {"href": str(DEM), "type": "image/tiff; application=geotiff"},
        "outlets": [{"site_id": "valley", "x": OUTLET_X, "y": OUTLET_Y}],
        "crs_project": "EPSG:2154",
        "dem_correction_type": "breach",
        "snap_distance_m": 100,
    }
    inputs.update(overrides.pop("inputs", {}))  # type: ignore[arg-type]
    document: dict[str, object] = {
        "process": {"id": "terrain-delineate", "version": "1.0.0"},
        "inputs": inputs,
    }
    document.update(overrides)
    return document


def _staged(tmp_path: Path, document: dict, *, name: str = "job") -> JobDirectory:
    job = JobDirectory.create(tmp_path / name)
    job.request_path.write_text(json.dumps(document), encoding="utf-8")
    return job


@pytest.fixture
def sealed_job(tmp_path):
    job = _staged(tmp_path, _request())
    outcome = run(job, exit_code_for=exit_code_for)
    assert outcome.status == "successful", outcome.errors
    return job, outcome


def test_a_job_that_finished_is_sealed_and_verifies_against_its_own_seal(sealed_job):
    job, _ = sealed_job

    assert job.is_sealed
    assert verify_job(job).ok


def test_the_directory_carries_only_the_names_the_layout_allows(sealed_job):
    job, _ = sealed_job

    assert {entry.name for entry in job.root.iterdir()} <= ALLOWED_JOB_ENTRIES


def test_outputs_holds_the_declared_artefacts_and_nothing_else(sealed_job):
    job, _ = sealed_job
    declared = {
        output.path.removeprefix("outputs/")
        for output in TERRAIN_DELINEATE.outputs
        if output.path.startswith("outputs/")
    }

    assert {entry.name for entry in job.outputs_dir.iterdir()} == declared


def test_the_seal_and_the_outcome_name_one_job(sealed_job):
    job, outcome = sealed_job
    manifest = read_document(job.manifest_path)

    assert manifest["job_id"] == outcome.job_id
    assert read_document(job.outcome_path)["job_id"] == outcome.job_id
    assert outcome.job_id.startswith("sha256:")


def test_the_outcome_hashes_every_artefact_the_seal_hashes(sealed_job):
    job, outcome = sealed_job
    manifest = read_document(job.manifest_path)
    sealed = {entry["path"]: entry["sha256"] for entry in manifest["artifacts"]}

    for record in outcome.outputs:
        assert sealed[record.path] == record.sha256


def test_outcome_json_is_sealed_although_it_can_carry_no_digest_of_itself(sealed_job):
    job, outcome = sealed_job
    manifest = read_document(job.manifest_path)
    sealed = {entry["path"] for entry in manifest["artifacts"]}

    assert "outcome.json" in sealed
    assert "outcome.json" not in {record.path for record in outcome.outputs}
    digest, _ = sha256_file(job.outcome_path)
    entry = next(one for one in manifest["artifacts"] if one["path"] == "outcome.json")
    assert entry["sha256"] == digest


def test_a_stranger_opens_the_catchment_with_geopandas_alone(sealed_job):
    job, _ = sealed_job

    frame = gpd.read_file(job.outputs_dir / "watershed.gpkg")

    assert list(frame["site_id"]) == ["valley"]
    assert str(frame.crs) == "EPSG:2154"
    assert frame["area_m2"].iloc[0] > 0.0
    assert not frame.geometry.iloc[0].is_empty


def test_the_columnar_catchment_carries_the_same_rows(sealed_job):
    job, _ = sealed_job

    table = gpd.read_parquet(job.outputs_dir / "watershed.parquet")
    frame = gpd.read_file(job.outputs_dir / "watershed.gpkg")

    assert list(table["site_id"]) == list(frame["site_id"])
    assert table["area_m2"].tolist() == pytest.approx(frame["area_m2"].tolist())


def test_the_snapped_outlets_are_published_in_the_one_geojson_crs(sealed_job):
    job, _ = sealed_job

    payload = json.loads((job.outputs_dir / "outlets_snapped.geojson").read_text(encoding="utf-8"))
    (feature,) = payload["features"]
    longitude, latitude = feature["geometry"]["coordinates"]

    assert -180.0 <= longitude <= 180.0
    assert -90.0 <= latitude <= 90.0
    assert feature["properties"]["site_id"] == "valley"
    assert feature["properties"]["status"] == "delineated"
    assert feature["properties"]["x_outlet"] == OUTLET_X
    assert feature["properties"]["x_snapped"] != OUTLET_X
    assert feature["properties"]["snap_distance_m"] > 0.0


def test_an_outlet_that_produced_nothing_is_named_in_a_declared_artefact(tmp_path):
    """A partial batch succeeds, and says which outlets produced no catchment.

    Refusing the whole job over one bad coordinate would throw away the work
    of every other outlet. Reporting the loss only in the prose of
    ``warnings`` would make a machine parse sentences to find out what it
    got, which is the defect the roll call exists to close.
    """
    job = _staged(
        tmp_path,
        _request(
            inputs={
                "outlets": [
                    {"site_id": "valley", "x": OUTLET_X, "y": OUTLET_Y},
                    {"site_id": "elsewhere", "x": 0.0, "y": 0.0},
                ]
            }
        ),
    )

    outcome = run(job, exit_code_for=exit_code_for)

    assert outcome.status == "successful"
    assert job.is_sealed
    payload = json.loads((job.outputs_dir / "outlets_snapped.geojson").read_text(encoding="utf-8"))
    by_site = {one["properties"]["site_id"]: one["properties"] for one in payload["features"]}
    assert set(by_site) == {"valley", "elsewhere"}
    assert by_site["valley"]["status"] == "delineated"
    assert by_site["elsewhere"]["status"] != "delineated"
    assert by_site["elsewhere"]["failure_reason"]
    assert by_site["elsewhere"]["snap_distance_m"] is None
    # The catchment layer holds the outlets that produced a polygon, and only those.
    assert list(gpd.read_file(job.outputs_dir / "watershed.gpkg")["site_id"]) == ["valley"]
    assert any("elsewhere" in warning for warning in outcome.warnings)


def test_the_provenance_names_the_engine_that_did_the_work(sealed_job):
    job, _ = sealed_job

    provenance = read_document(job.provenance_path)

    assert provenance["backend"]["name"] == "whitebox_workflows"
    assert provenance["backend"]["digest"]
    assert provenance["job_id"] == read_document(job.manifest_path)["job_id"]


def test_the_input_set_hashes_the_dem_that_was_read(sealed_job):
    job, _ = sealed_job
    digest, size = sha256_file(DEM)

    resources = {one["name"]: one for one in read_document(job.inputset_path)["resources"]}

    assert resources["dem"]["sha256"] == digest
    assert resources["dem"]["bytes"] == size
    assert resources["parameters"]["href"] == "request.json#/inputs"


def test_two_requests_that_ask_for_the_same_work_carry_one_job_id(tmp_path):
    """A member left out and the same member written at its default are one job.

    The content address is computed over the **effective** inputs, which is
    what makes the reuse short-circuit of ``job_id`` mean "this work was
    already done" rather than "this document was already seen".
    """
    spelled = _request(inputs={"dem_correction_type": "breach", "snap_distance_m": 50})
    omitted = _request()
    del omitted["inputs"]["dem_correction_type"]  # type: ignore[union-attr]
    del omitted["inputs"]["snap_distance_m"]  # type: ignore[union-attr]

    first = run(_staged(tmp_path, spelled, name="a"), exit_code_for=exit_code_for)
    second = run(_staged(tmp_path, omitted, name="b"), exit_code_for=exit_code_for)

    assert first.status == "successful"
    assert second.status == "successful"
    assert first.job_id == second.job_id


def test_a_dem_that_is_not_there_fails_the_job_and_seals_nothing(tmp_path):
    job = _staged(tmp_path, _request(inputs={"dem": {"href": "absent.tif"}}))

    outcome = run(job, exit_code_for=exit_code_for)

    assert outcome.status == "failed"
    assert outcome.exit_code == EXIT_NOT_FOUND
    assert not job.is_sealed
    assert read_document(job.outcome_path)["status"] == "failed"


def test_a_dem_whose_bytes_are_not_the_pinned_ones_fails_the_job(tmp_path):
    job = _staged(
        tmp_path,
        _request(inputs={"dem": {"href": str(DEM), "sha256": "0" * 64}}),
    )

    outcome = run(job, exit_code_for=exit_code_for)

    assert outcome.status == "failed"
    assert outcome.exit_code == EXIT_VALIDATION
    assert not job.is_sealed


def test_an_output_nobody_declares_is_refused_before_the_run(tmp_path):
    job = _staged(tmp_path, _request(outputs={"hillshade": {}}))

    outcome = run(job, exit_code_for=exit_code_for)

    assert outcome.status == "failed"
    assert outcome.exit_code == EXIT_CONFIG
    assert not job.outputs_dir.exists()
    assert outcome.errors[0]["details"][0]["pointer"] == "/outputs/hillshade"


def test_an_outlet_outside_the_dem_fails_as_a_backend_failure_not_as_a_bug(tmp_path):
    job = _staged(
        tmp_path,
        _request(inputs={"outlets": [{"site_id": "elsewhere", "x": 0.0, "y": 0.0}]}),
    )

    outcome = run(job, exit_code_for=exit_code_for)

    assert outcome.status == "failed"
    assert outcome.exit_code == EXIT_SOLVER_ERROR
    assert not job.is_sealed


def test_a_request_that_targets_another_capability_is_refused(tmp_path):
    document = _request()
    document["process"] = {"id": "data-fetch", "version": "1.0.0"}
    job = _staged(tmp_path, document)

    outcome = run(job, exit_code_for=exit_code_for)

    assert outcome.status == "failed"
    assert outcome.exit_code == EXIT_CONFIG


def test_an_envelope_member_this_process_ignores_is_a_warning_not_a_refusal(tmp_path):
    job = _staged(tmp_path, _request(subscriber={"successUri": "https://example.invalid/done"}))

    outcome = run(job, exit_code_for=exit_code_for)

    assert outcome.status == "successful"
    assert any("subscriber" in warning for warning in outcome.warnings)


def test_a_failure_after_the_inputs_resolved_keeps_the_job_id(tmp_path, monkeypatch):
    """A job that failed at its work is still the job that was asked for.

    The content address is computed before anything runs, so an outcome that
    reported ``unidentified`` after the terrain engine failed would throw away
    an id the process already held -- and with it every chance for a caller to
    match the failure against the request that caused it.
    """
    from hydromodpy.spatial.site_selection.hydrology import worker

    def explode(*args, **kwargs):
        raise RuntimeError("the engine gave up")

    monkeypatch.setattr(worker, "_produce", explode)
    job = _staged(tmp_path, _request())

    outcome = run(job, exit_code_for=exit_code_for)

    assert outcome.status == "failed"
    assert outcome.job_id.startswith("sha256:")
    assert outcome.job_id == run_job_id_of(tmp_path)


def run_job_id_of(tmp_path: Path) -> str:
    """The job id the same request carries when it succeeds."""
    job = _staged(tmp_path, _request(), name="reference")
    return run(job, exit_code_for=exit_code_for).job_id


def test_a_request_whose_inputs_never_resolved_carries_no_job_id(tmp_path):
    job = _staged(tmp_path, _request(inputs={"dem": {"href": "absent.tif"}}))

    outcome = run(job, exit_code_for=exit_code_for)

    assert outcome.job_id == UNIDENTIFIED_JOB


def test_the_same_request_into_a_sealed_directory_is_reused_and_not_re_run(sealed_job):
    """The short-circuit, on the only thing that can prove it: the disk.

    Not a delay and not a spy on the engine. A re-run would rewrite every
    artefact and every document, so "nothing changed, to the byte" is both the
    strongest statement available and the exact promise §1.9 makes.
    """
    job, first = sealed_job
    before = {
        path.relative_to(job.root).as_posix(): path.read_bytes()
        for path in sorted(job.root.rglob("*"))
        if path.is_file()
    }

    second = run(job, exit_code_for=exit_code_for)

    assert second.reused is True
    assert second.exit_code == 0
    assert second.status == "successful"
    assert second.job_id == first.job_id
    after = {
        path.relative_to(job.root).as_posix(): path.read_bytes()
        for path in sorted(job.root.rglob("*"))
        if path.is_file()
    }
    assert after == before


def test_the_reused_outcome_carries_what_the_first_run_recorded(sealed_job):
    """Re-reported and not re-derived: the artefacts are the ones on disk."""
    job, first = sealed_job

    second = run(job, exit_code_for=exit_code_for)

    assert [record.to_document() for record in second.outputs] == [
        record.to_document() for record in first.outputs
    ]
    assert second.started_at == first.started_at
    assert second.finished_at == first.finished_at
    assert read_document(job.outcome_path)["reused"] is False


def test_a_different_request_into_a_sealed_directory_is_refused(sealed_job):
    """One job, one directory. Another job would overwrite a finished seal."""
    job, first = sealed_job
    before = job.manifest_path.read_bytes()
    job.request_path.write_text(
        json.dumps(_request(inputs={"snap_distance_m": 75})), encoding="utf-8"
    )

    with pytest.raises(JobUsageError) as caught:
        run(job, exit_code_for=exit_code_for)

    assert first.job_id in str(caught.value)
    assert job.manifest_path.read_bytes() == before
    assert read_document(job.outcome_path)["job_id"] == first.job_id


def test_a_signal_during_the_reuse_decision_publishes_no_stale_document(sealed_job, monkeypatch):
    """Exit 130 and a document saying ``successful`` cannot both be true.

    Answering a sealed directory now costs one pass over the DEM, to compute
    the content address, and that is a window an asynchronous signal can land
    in. ``TerminationRequested`` subclasses ``KeyboardInterrupt``, so it is a
    sibling of ``Exception`` and no ``except Exception`` catches it: it unwinds
    out of the capability and reaches the runtime, which prints ``outcome.json``
    beside exit 130. On a sealed directory that file is the **finished** job's
    outcome -- ``successful``, exit 0 -- and printing it would contradict the
    code the caller was just handed.

    Nothing may be written either: the directory belongs to a job that finished.
    So the only honest answer is 130 and an empty stdout, which is exactly what
    the e2e test of a signal arriving before the run starts already asserts.
    """
    from hydromodpy.cli._workers.process import run_capability
    from hydromodpy.core.interrupts import TerminationRequested
    from hydromodpy.spatial.site_selection.hydrology import worker

    job, _ = sealed_job
    sealed = job.manifest_path.read_bytes()
    finished = job.outcome_path.read_bytes()

    def cancelled(*args, **kwargs):
        raise TerminationRequested("signal 15")

    monkeypatch.setattr(worker, "_resolve", cancelled)

    exit_code, payload = run_capability("terrain-delineate", job.root)

    assert exit_code == 130
    assert payload == ""
    assert job.manifest_path.read_bytes() == sealed
    assert job.outcome_path.read_bytes() == finished


def test_a_request_that_no_longer_resolves_cannot_reuse_a_seal(sealed_job):
    """Unaddressable is not the same as matching, and must not be answered as one."""
    job, _ = sealed_job
    before = job.outcome_path.read_bytes()
    job.request_path.write_text(
        json.dumps(_request(inputs={"crs_project": "lambert93"})), encoding="utf-8"
    )

    with pytest.raises(JobUsageError):
        run(job, exit_code_for=exit_code_for)

    assert job.outcome_path.read_bytes() == before


def test_a_dem_that_is_not_a_raster_is_bad_input_and_not_an_internal_bug(tmp_path):
    """Exit 1 means "report this as a bug here". A text file is not that."""
    impostor = tmp_path / "not-a-raster.tif"
    impostor.write_text("elevation, more or less\n", encoding="utf-8")
    job = _staged(tmp_path, _request(inputs={"dem": {"href": str(impostor)}}))

    outcome = run(job, exit_code_for=exit_code_for)

    assert outcome.status == "failed"
    assert outcome.exit_code == EXIT_VALIDATION
    assert outcome.errors[0]["code"] == DataContractViolation.code
    assert not job.is_sealed


@pytest.mark.allow_subprocess
def test_the_capability_writes_nothing_into_the_home_it_is_given(tmp_path):
    """The one confinement guarantee that only a fresh process can show.

    ``hmp run`` registers every project it touches into a machine-wide DuckDB
    under the user's state directory. A capability inherits none of that, and
    the only honest way to say so is to hand it an empty ``HOME`` and an empty
    ``XDG_STATE_HOME`` and look at them afterwards.
    """
    home = tmp_path / "home"
    state = tmp_path / "state"
    home.mkdir()
    state.mkdir()
    job = _staged(tmp_path, _request())

    script = (
        "from hydromodpy.cli.helpers import exit_code_for\n"
        "from hydromodpy.schema.job import JobDirectory\n"
        "from hydromodpy.spatial.site_selection.hydrology.worker import run\n"
        "import sys\n"
        "outcome = run(JobDirectory.open(sys.argv[1]), exit_code_for=exit_code_for)\n"
        "sys.exit(outcome.exit_code)\n"
    )
    env = dict(os.environ, HOME=str(home), XDG_STATE_HOME=str(state), HMP_NO_PROGRESS="1")
    completed = subprocess.run(
        [sys.executable, "-c", script, str(job.root)],
        env=env,
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr[-4000:]
    assert job.is_sealed
    assert list(home.iterdir()) == []
    assert list(state.iterdir()) == []


def test_the_only_thing_it_writes_outside_the_job_is_what_it_declares(tmp_path):
    """The declaration of scratch space is checked, not asserted in prose.

    ``writes_outside_jobdir`` said ``false`` when the generator first wrote it,
    and it was false: the delineation assembles one catchment per outlet under a
    ``TemporaryDirectory``, which lands under ``TMPDIR`` and not under the job.
    An orchestrator mounting everything but the job directory read-only would
    have followed that boolean into a crash.

    A subprocess, because ``tempfile`` caches its directory on first use and
    this test process has already used it.
    """
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    created = tmp_path / "created.json"
    job = _staged(tmp_path, _request())

    script = (
        "import json, os, sys, tempfile\n"
        "seen = []\n"
        "real_dir, real_file = tempfile.mkdtemp, tempfile.mkstemp\n"
        "def spy_dir(*a, **k):\n"
        "    path = real_dir(*a, **k)\n"
        "    seen.append(path)\n"
        "    return path\n"
        "def spy_file(*a, **k):\n"
        "    handle, path = real_file(*a, **k)\n"
        "    seen.append(path)\n"
        "    return handle, path\n"
        "tempfile.mkdtemp, tempfile.mkstemp = spy_dir, spy_file\n"
        "from hydromodpy.cli.helpers import exit_code_for\n"
        "from hydromodpy.schema.job import JobDirectory\n"
        "from hydromodpy.spatial.site_selection.hydrology.worker import run\n"
        "try:\n"
        "    outcome = run(JobDirectory.open(sys.argv[1]), exit_code_for=exit_code_for)\n"
        "finally:\n"
        "    open(sys.argv[2], 'w').write(json.dumps(seen))\n"
        "sys.exit(outcome.exit_code)\n"
    )
    env = dict(os.environ, TMPDIR=str(scratch), HMP_NO_PROGRESS="1")
    completed = subprocess.run(
        [sys.executable, "-c", script, str(job.root), str(created)],
        env=env,
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr[-4000:]
    paths = [Path(entry).resolve() for entry in json.loads(created.read_text(encoding="utf-8"))]

    # Derived from the declaration, never hard-coded: with ``writes_outside_jobdir``
    # emptied, ``allowed`` shrinks to the job directory and this test goes red,
    # which is the whole point of writing it.
    known = {"$TMPDIR": scratch.resolve()}
    unknown = set(TERRAIN_DELINEATE.writes_outside_jobdir) - set(known)
    assert not unknown, f"this test cannot point at the declared location(s) {sorted(unknown)}"
    allowed = [job.root.resolve()] + [
        known[name] for name in TERRAIN_DELINEATE.writes_outside_jobdir
    ]

    outside = [path for path in paths if not any(path.is_relative_to(root) for root in allowed)]
    assert not outside, f"it writes into {outside}, which it does not declare"
    assert any(path.is_relative_to(scratch.resolve()) for path in paths), (
        "nothing landed under TMPDIR, so declaring it over-claims"
    )
    assert list(scratch.iterdir()) == [], "the scratch survived the job"


LOCAL_NAMES = frozenset({"localhost", "localhost.localdomain", "ip6-localhost"})
"""Names of the local machine. Not egress: reachable with no route out at all."""

CHILD_PROCESSES_THE_JOB_SPAWNS = ("git", "uname")
"""The executables the capability runs, and the ceiling of the two socket spies.

A child process has its own interpreter and its own sockets, so patching
``socket`` in the parent says nothing about what it does -- which makes this
list, not the spies, what holds the guarantee for that path. Both entries are
measured, and the second was found by this assertion rather than by reading:

- ``git``, twice, from ``schema/job/provenance.py``: ``rev-parse`` and
  ``status --porcelain``, to record which revision did the work.
- ``uname -p``, from the standard library and not from this repository.
  ``platform.platform()`` unpacks ``uname_result``, whose ``processor`` member is
  a ``cached_property`` that falls back to ``subprocess.check_output(('uname',
  '-p'))``. Reading the provenance code finds no subprocess at all.

A capability that shells out to ``curl`` lands in this assertion by name rather
than passing unseen, which is the whole reason the list is pinned.
"""


def _is_local(value: object) -> bool:
    """True when *value* names this machine, in any of its spellings.

    Semantic and not a string set: ``127.0.0.2``, ``::ffff:127.0.0.1`` and the
    integer form ``2130706433`` are all loopback, and flagging one of them as
    egress would turn this gate red for a reason that has nothing to do with the
    capability under test.
    """
    text = str(value).casefold().rstrip(".")
    if text in LOCAL_NAMES:
        return True
    try:
        return ipaddress.ip_address(text).is_loopback
    except ValueError:
        pass
    try:
        return ipaddress.ip_address(int(text, 0)).is_loopback
    except (ValueError, TypeError):
        return False


def test_the_only_hosts_it_contacts_are_the_ones_it_declares(tmp_path):
    """The confinement guarantee that had been prose since the day it was written.

    ``worker.py`` says "it reaches no network" in its own docstring, and the
    specification asked the description to say ``network: "forbidden"``. Neither
    was checked by anything, so the member was kept out of the published
    description rather than shipped unbacked. This is what lets it in.

    Three angles, because two are not enough: a host resolved through
    ``getaddrinfo`` is caught by name, a connection opened straight to a
    hardcoded address resolves nothing and is caught by address, and a child
    process does its networking in an interpreter this one cannot patch, so it is
    caught by the name of the executable instead.

    A subprocess, and a sentinel before the run: a spy that silently fails to
    install would make this test pass on any capability at all, so the spy is
    made to catch a resolution and a connection of the harness's own before the
    recording is cleared and the capability starts.

    That every served capability has a gate of this name is pinned one level up,
    in ``tests/unit/schema/test_capability_egress_gates.py``: the claim is about
    the registry, and it could not name the gate of a capability whose tests live
    in another file.
    """
    seen = tmp_path / "seen.json"
    job = _staged(tmp_path, _request())

    script = (
        "import json, socket, subprocess, sys\n"
        "names, addrs, spawned = [], [], []\n"
        "real_addrinfo, real_connect = socket.getaddrinfo, socket.socket.connect\n"
        "real_popen = subprocess.Popen.__init__\n"
        "def spy_addrinfo(host, port, *a, **k):\n"
        "    names.append([host, port])\n"
        "    return real_addrinfo(host, port, *a, **k)\n"
        "def spy_connect(self, address, *a, **k):\n"
        "    addrs.append(list(address) if isinstance(address, tuple) else [address])\n"
        "    return real_connect(self, address, *a, **k)\n"
        "def spy_popen(self, args, *a, **k):\n"
        "    spawned.append(args if isinstance(args, str) else list(args))\n"
        "    return real_popen(self, args, *a, **k)\n"
        "socket.getaddrinfo, socket.socket.connect = spy_addrinfo, spy_connect\n"
        "subprocess.Popen.__init__ = spy_popen\n"
        # The sentinel. Loopback only, so it needs no route off the machine.
        "socket.getaddrinfo('localhost', 9)\n"
        "probe = socket.socket()\n"
        "try:\n"
        "    probe.connect(('127.0.0.1', 9))\n"
        "except OSError:\n"
        "    pass\n"  # Refused is the expected answer and proves the spy fired.
        "finally:\n"
        "    probe.close()\n"
        "subprocess.run([sys.executable, '-c', ''], capture_output=True)\n"
        "sentinel = {'names': list(names), 'addrs': list(addrs), 'spawned': list(spawned)}\n"
        "names.clear()\n"
        "addrs.clear()\n"
        "spawned.clear()\n"
        "from hydromodpy.cli.helpers import exit_code_for\n"
        "from hydromodpy.schema.job import JobDirectory\n"
        "from hydromodpy.spatial.site_selection.hydrology.worker import run\n"
        "try:\n"
        "    outcome = run(JobDirectory.open(sys.argv[1]), exit_code_for=exit_code_for)\n"
        "finally:\n"
        "    open(sys.argv[2], 'w').write(\n"
        "        json.dumps(\n"
        "            {\n"
        "                'sentinel': sentinel,\n"
        "                'names': names,\n"
        "                'addrs': addrs,\n"
        "                'spawned': spawned,\n"
        "            }\n"
        "        )\n"
        "    )\n"
        "sys.exit(outcome.exit_code)\n"
    )
    env = dict(os.environ, HMP_NO_PROGRESS="1")
    completed = subprocess.run(
        [sys.executable, "-c", script, str(job.root), str(seen)],
        env=env,
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr[-4000:]
    recorded = json.loads(seen.read_text(encoding="utf-8"))
    sentinel = recorded["sentinel"]
    assert sentinel["names"] and sentinel["addrs"] and sentinel["spawned"], (
        "a spy caught nothing of the harness's own, so it is not installed"
    )
    # The sentinel is kept and read, not reduced to a boolean: it contacted the
    # local machine by name and by address, so it is also the one case that
    # exercises the locality filter below. A broken filter would otherwise sit
    # unnoticed behind a run that resolves nothing at all.
    assert all(_is_local(entry[0]) for entry in sentinel["names"] + sentinel["addrs"]), (
        "the locality filter does not recognise the local machine it was handed"
    )

    declared = set(TERRAIN_DELINEATE.reaches_network)
    # Locality is subtracted on both socket angles, and for the same reason: a
    # local name and a local address are the same non-egress, and exempting one
    # while flagging the other would make the gate depend on which of the two
    # spellings a library happened to use.
    undeclared = sorted(
        {str(entry[0]) for entry in recorded["names"] if not _is_local(entry[0])} - declared
    )
    assert not undeclared, f"it resolves {undeclared}, which it does not declare"
    # An address is read apart from a name: a connection to a literal address
    # resolves nothing, so the list above would stay empty while the process
    # reached the network anyway. Indexed and not unpacked, because an IPv6
    # address is a four-member tuple and a unix socket is a bare path.
    egress = sorted(
        {str(entry[0]) for entry in recorded["addrs"] if not _is_local(entry[0])} - declared
    )
    assert not egress, f"it connects to {egress}, which it does not declare"
    # And the ceiling of both: a child fetches in an interpreter this one never
    # patched, so what holds here is that the set of children is the measured one.
    children = sorted(
        {Path(argv[0] if isinstance(argv, list) else argv).name for argv in recorded["spawned"]}
    )
    assert children == sorted(CHILD_PROCESSES_THE_JOB_SPAWNS), (
        f"it spawns {children}, and only {sorted(CHILD_PROCESSES_THE_JOB_SPAWNS)} is accounted for"
    )


def test_every_declared_capability_carries_a_body() -> None:
    """The two lists of the registry, pinned through the public door.

    ``capability_decls()`` imports no engine and ``_registry()`` imports every
    worker, so the pairing is by identifier and nothing structural holds it. A
    declaration renamed on one side alone used to raise a bare ``KeyError`` out
    of the registry comprehension -- for every capability, not the renamed one,
    and mapped to the generic exit 1 rather than the usage exit 2.
    """
    from hydromodpy.cli._workers.process import capability, capability_decls, capability_ids

    assert capability_ids() == tuple(sorted(decl.id for decl in capability_decls()))
    for capability_id in capability_ids():
        assert capability(capability_id).decl.id == capability_id


def test_a_declaration_without_a_body_names_itself(monkeypatch) -> None:
    from hydromodpy.cli._workers import process as worker_module

    ghost = TERRAIN_DELINEATE.__class__(
        id="ghost-capability",
        version="1.0.0",
        title="Declared and never implemented",
        description="A declaration with no body, which is a build defect.",
        keywords=(),
        request_model=TERRAIN_DELINEATE.request_model,
        outputs=TERRAIN_DELINEATE.outputs,
        exceptions=TERRAIN_DELINEATE.exceptions,
    )
    monkeypatch.setattr(worker_module, "capability_decls", lambda: (TERRAIN_DELINEATE, ghost))

    with pytest.raises(RuntimeError, match="'ghost-capability' is declared but this build"):
        worker_module.capability("terrain-delineate")
