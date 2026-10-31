"""``terrain-delineate`` as an orchestrator invokes it: one directory in, one seal out.

The outputs are read with ``geopandas`` and ``json`` alone. ``dem_valley.tif`` is 100 x 100
cells of 25 m in EPSG:2154 draining west to (300012.5, 6701262.5); the outlet sits 100 m
east of the talweg so the snap has something to do.
"""

from __future__ import annotations

import contextlib
import ipaddress
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from hydromodpy.cli import helpers as codes
from hydromodpy.cli.helpers import exit_code_for
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
OUTLET_X, OUTLET_Y = 300112.5, 6701262.5
VALLEY = {"site_id": "valley", "x": OUTLET_X, "y": OUTLET_Y}
ELSEWHERE = {"site_id": "elsewhere", "x": 0.0, "y": 0.0}


def _request(**overrides: object) -> dict:
    inputs: dict[str, object] = {
        "dem": {"href": str(DEM), "type": "image/tiff; application=geotiff"},
        "outlets": [VALLEY],
        "crs_project": "EPSG:2154",
        "dem_correction_type": "breach",
        "snap_distance_m": 100,
    }
    inputs.update(overrides.pop("inputs", {}))  # type: ignore[arg-type]
    return {
        "process": {"id": "terrain-delineate", "version": "1.1.0"},
        "inputs": inputs,
    } | overrides


def _staged(tmp_path: Path, document: dict, *, name: str = "job") -> JobDirectory:
    job = JobDirectory.create(tmp_path / name)
    job.request_path.write_text(json.dumps(document), encoding="utf-8")
    return job


def _run(tmp_path: Path, document: dict, *, name: str = "job"):
    job = _staged(tmp_path, document, name=name)
    return job, run(job, exit_code_for=exit_code_for)


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def sealed_job(tmp_path):
    job, outcome = _run(tmp_path, _request())
    assert outcome.status == "successful", outcome.errors
    return job, outcome


def test_a_job_that_finished_is_sealed_and_read_by_a_stranger_alone(sealed_job):
    """The seal and the outcome name one job, and outcome.json is sealed with no digest of itself.

    The GeoPackage and the GeoParquet carry the same rows; the GeoJSON is in WGS 84.
    """
    job, outcome = sealed_job
    manifest = read_document(job.manifest_path)
    sealed = {entry["path"]: entry["sha256"] for entry in manifest["artifacts"]}
    declared = {
        one.path.removeprefix("outputs/")
        for one in TERRAIN_DELINEATE.outputs
        if one.path.startswith("outputs/")
    }

    assert job.is_sealed and verify_job(job).ok
    assert {entry.name for entry in job.root.iterdir()} <= ALLOWED_JOB_ENTRIES
    assert {entry.name for entry in job.outputs_dir.iterdir()} == declared
    assert manifest["job_id"] == read_document(job.outcome_path)["job_id"] == outcome.job_id
    assert outcome.job_id.startswith("sha256:")
    for record in outcome.outputs:
        assert sealed[record.path] == record.sha256
    assert "outcome.json" not in {record.path for record in outcome.outputs}
    assert sealed["outcome.json"] == sha256_file(job.outcome_path)[0]
    provenance = read_document(job.provenance_path)
    assert provenance["backend"]["name"] == "whitebox_workflows"
    assert provenance["backend"]["digest"]
    assert provenance["job_id"] == manifest["job_id"]
    resources = {one["name"]: one for one in read_document(job.inputset_path)["resources"]}
    assert (resources["dem"]["sha256"], resources["dem"]["bytes"]) == sha256_file(DEM)
    assert resources["parameters"]["href"] == "request.json#/inputs"
    frame = gpd.read_file(job.outputs_dir / "watershed.gpkg")
    table = gpd.read_parquet(job.outputs_dir / "watershed.parquet")
    (feature,) = _json(job.outputs_dir / "outlets_snapped.geojson")["features"]
    longitude, latitude = feature["geometry"]["coordinates"]
    properties = feature["properties"]

    assert list(frame["site_id"]) == list(table["site_id"]) == ["valley"]
    assert str(frame.crs) == "EPSG:2154"
    assert frame["area_m2"].iloc[0] > 0.0
    assert not frame.geometry.iloc[0].is_empty
    assert table["area_m2"].tolist() == pytest.approx(frame["area_m2"].tolist())
    assert -180.0 <= longitude <= 180.0 and -90.0 <= latitude <= 90.0
    assert (properties["site_id"], properties["status"]) == ("valley", "delineated")
    assert properties["x_outlet"] == OUTLET_X != properties["x_snapped"]
    assert properties["snap_distance_m"] > 0.0


def test_an_outlet_that_produced_nothing_is_named_in_a_declared_artefact(tmp_path):
    """A partial batch succeeds and names, in a file, the outlets that gave no catchment.

    A machine should not parse the prose of ``warnings`` to find out what it got.
    The ``subscriber`` member this process ignores is a warning, not a refusal.
    """
    outlets = [VALLEY, ELSEWHERE]
    subscriber = {"successUri": "https://example.invalid/done"}
    job, outcome = _run(tmp_path, _request(inputs={"outlets": outlets}, subscriber=subscriber))

    assert outcome.status == "successful" and job.is_sealed
    features = _json(job.outputs_dir / "outlets_snapped.geojson")["features"]
    by_site = {one["properties"]["site_id"]: one["properties"] for one in features}
    assert set(by_site) == {"valley", "elsewhere"}
    assert by_site["valley"]["status"] == "delineated" != by_site["elsewhere"]["status"]
    assert by_site["elsewhere"]["failure_reason"]
    assert by_site["elsewhere"]["snap_distance_m"] is None
    # The catchment layer holds the outlets that produced a polygon, and only those.
    assert list(gpd.read_file(job.outputs_dir / "watershed.gpkg")["site_id"]) == ["valley"]
    assert any("elsewhere" in warning for warning in outcome.warnings)
    assert any("subscriber" in warning for warning in outcome.warnings)


def test_two_requests_that_ask_for_the_same_work_carry_one_job_id(tmp_path):
    """A member left out and the same member written at its default are one job.

    The address is computed over the effective inputs, so a reused ``job_id``
    means "this work was already done", not "this document was already seen".
    """
    omitted = _request()
    del omitted["inputs"]["dem_correction_type"], omitted["inputs"]["snap_distance_m"]
    spelled = _request(inputs={"dem_correction_type": "breach", "snap_distance_m": 50})

    _, first = _run(tmp_path, spelled, name="a")
    _, second = _run(tmp_path, omitted, name="b")

    assert first.status == second.status == "successful"
    assert first.job_id == second.job_id


def _not_a_raster(tmp_path: Path) -> dict:
    impostor = tmp_path / "not-a-raster.tif"
    impostor.write_text("elevation, more or less\n", encoding="utf-8")
    return _request(inputs={"dem": {"href": str(impostor)}})


@pytest.mark.parametrize(
    ("document", "exit_code", "detail"),
    [
        pytest.param(lambda _: _request(inputs={"dem": {"href": "absent.tif"}}),
                     codes.EXIT_NOT_FOUND, "absent.tif", id="absent_dem"),
        pytest.param(lambda _: _request(inputs={"dem": {"href": str(DEM), "sha256": "0" * 64}}),
                     codes.EXIT_VALIDATION, "0" * 64, id="dem_bytes_not_pinned"),
        pytest.param(lambda _: _request(outputs={"hillshade": {}}),
                     codes.EXIT_CONFIG, "/outputs/hillshade", id="undeclared_output"),
        pytest.param(lambda _: _request(inputs={"outlets": [ELSEWHERE]}),
                     codes.EXIT_SOLVER_ERROR, None, id="outlet_outside_the_dem"),
        pytest.param(lambda _: _request() | {"process": {"id": "data-request", "version": "1.0.0"}},
                     codes.EXIT_CONFIG, "data-request", id="another_capability"),
        pytest.param(_not_a_raster, codes.EXIT_VALIDATION, DataContractViolation.code,
                     id="dem_not_a_raster"),
        pytest.param(lambda _: _request(inputs={"engine": "numpy_d8"}),
                     codes.EXIT_SOLVER_ERROR, "breach", id="engine_without_breach"),
        pytest.param(lambda _: _request(inputs={"engine": "pysheds"}),
                     codes.EXIT_CONFIG, "pysheds", id="engine_nobody_installed"),
    ],
)  # fmt: skip
def test_a_job_that_cannot_be_done_fails_with_its_typed_code_and_seals_nothing(
    tmp_path, document, exit_code, detail
):
    """A typed code, never exit 1, and no job id when the inputs never resolved.

    An engine refuses by name an option it cannot serve; one nobody installed writes nothing.
    """
    job, outcome = _run(tmp_path, document(tmp_path))

    assert (outcome.status, outcome.exit_code) == ("failed", exit_code)
    assert not job.is_sealed
    assert read_document(job.outcome_path)["status"] == "failed"
    if detail is not None:
        assert detail in json.dumps(outcome.errors)
    if exit_code in {codes.EXIT_NOT_FOUND, codes.EXIT_CONFIG}:
        assert not (job.outputs_dir / "dem_corrected.tif").exists()
    if detail == "absent.tif":
        assert (outcome.job_id, outcome.errors[0]["code"]) == (UNIDENTIFIED_JOB, "HMPY.E211")
    if detail == "/outputs/hillshade":
        assert not job.outputs_dir.exists()
        assert outcome.errors[0]["details"][0]["pointer"] == detail
    if detail == DataContractViolation.code:
        assert outcome.errors[0]["code"] == detail


def test_a_failure_after_the_inputs_resolved_keeps_the_job_id(sealed_job, tmp_path, monkeypatch):
    """The address is computed before anything runs, so the caller can match the failure."""
    from hydromodpy.spatial.site_selection.hydrology import worker

    def explode(*args, **kwargs):
        raise RuntimeError("the engine gave up")

    monkeypatch.setattr(worker, "build_site_selection_flow_products", explode)

    _, outcome = _run(tmp_path, _request(), name="failing")

    assert outcome.status == "failed"
    assert outcome.job_id.startswith("sha256:")
    assert outcome.job_id == sealed_job[1].job_id


def test_the_same_request_into_a_sealed_directory_is_reused_and_not_re_run(sealed_job):
    """Proved on the disk: nothing changes, to the byte, and the outcome re-reports the first run."""
    job, first = sealed_job

    def files() -> dict:
        paths = sorted(job.root.rglob("*"))
        return {one.relative_to(job.root).as_posix(): one.read_bytes() for one in paths if one.is_file()}  # fmt: skip

    before = files()

    second = run(job, exit_code_for=exit_code_for)

    assert (second.reused, second.exit_code, second.status) == (True, 0, "successful")
    assert second.job_id == first.job_id
    assert files() == before
    documents = [[record.to_document() for record in one.outputs] for one in (first, second)]
    assert documents[0] == documents[1]
    assert (second.started_at, second.finished_at) == (first.started_at, first.finished_at)
    assert read_document(job.outcome_path)["reused"] is False


@pytest.mark.parametrize(
    "member",
    [{"snap_distance_m": 75}, {"crs_project": "lambert93"}],
    ids=["a_different_request", "a_request_that_no_longer_resolves"],
)
def test_another_request_into_a_sealed_directory_is_refused(sealed_job, member):
    """One job, one directory, and an unaddressable request is not a matching one."""
    job, first = sealed_job
    before = (job.manifest_path.read_bytes(), job.outcome_path.read_bytes())
    job.request_path.write_text(json.dumps(_request(inputs=member)), encoding="utf-8")

    with pytest.raises(JobUsageError) as caught:
        run(job, exit_code_for=exit_code_for)

    assert (job.manifest_path.read_bytes(), job.outcome_path.read_bytes()) == before
    assert read_document(job.outcome_path)["job_id"] == first.job_id
    if "snap_distance_m" in member:
        assert first.job_id in str(caught.value)


# The job in a fresh interpreter; the spies put before it fill ``seen``.
CHILD = """
import json, sys
from hydromodpy.cli.helpers import exit_code_for
from hydromodpy.schema.job import JobDirectory
from hydromodpy.spatial.site_selection.hydrology.worker import run
try:
    outcome = run(JobDirectory.open(sys.argv[1]), exit_code_for=exit_code_for)
finally:
    open(sys.argv[2], "w").write(json.dumps(seen))
sys.exit(outcome.exit_code)
"""


def _run_in_a_child(tmp_path: Path, spies: str, **env: str):
    job, seen = _staged(tmp_path, _request()), tmp_path / "seen.json"
    completed = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(spies) + CHILD, str(job.root), str(seen)],
        env=dict(os.environ, HMP_NO_PROGRESS="1", **env), capture_output=True, text=True,
        timeout=600, check=False,
    )  # fmt: skip
    assert completed.returncode == 0, completed.stderr[-4000:]
    assert job.is_sealed
    return job, _json(seen)


@pytest.mark.allow_subprocess
def test_the_capability_writes_nothing_outside_the_job_but_its_declared_scratch(tmp_path):
    """Shown in a fresh process, since ``tempfile`` caches its directory on first use.

    Unlike ``hmp run``, a capability registers nothing in the user's state
    directory. Each catchment is assembled under a ``TemporaryDirectory``, so
    ``writes_outside_jobdir`` declares it for an orchestrator that mounts all
    but the job read-only.
    """
    home, state, scratch = (tmp_path / name for name in ("home", "state", "scratch"))
    for folder in (home, state, scratch):
        folder.mkdir()
    spies = """
        import tempfile
        seen = []
        real_dir, real_file = tempfile.mkdtemp, tempfile.mkstemp
        def spy_dir(*a, **k):
            path = real_dir(*a, **k)
            seen.append(path)
            return path
        def spy_file(*a, **k):
            handle, path = real_file(*a, **k)
            seen.append(path)
            return handle, path
        tempfile.mkdtemp, tempfile.mkstemp = spy_dir, spy_file
    """
    env = {"HOME": str(home), "XDG_STATE_HOME": str(state), "TMPDIR": str(scratch)}

    job, created = _run_in_a_child(tmp_path, spies, **env)

    assert list(home.iterdir()) == [] and list(state.iterdir()) == []
    paths = [Path(entry).resolve() for entry in created]
    # Derived from the declaration, never hard-coded: with ``writes_outside_jobdir``
    # emptied, ``allowed`` shrinks to the job directory and this test goes red.
    known = {"$TMPDIR": scratch.resolve()}
    unknown = set(TERRAIN_DELINEATE.writes_outside_jobdir) - set(known)
    assert not unknown, f"this test cannot point at the declared location(s) {sorted(unknown)}"
    allowed = [job.root.resolve()] + [known[one] for one in TERRAIN_DELINEATE.writes_outside_jobdir]
    outside = [path for path in paths if not any(path.is_relative_to(root) for root in allowed)]
    assert not outside, f"it writes into {outside}, which it does not declare"
    assert any(path.is_relative_to(scratch.resolve()) for path in paths), (
        "nothing landed under TMPDIR, so declaring it over-claims"
    )
    assert list(scratch.iterdir()) == [], "the scratch survived the job"


LOCAL_NAMES = frozenset({"localhost", "localhost.localdomain", "ip6-localhost"})
"""Names of the local machine. Not egress: reachable with no route out at all."""

CHILD_PROCESSES_THE_JOB_SPAWNS = ("git", Path(sys.executable).name, "uname")
"""The measured executables the job runs, which hold the guarantee for the children's sockets.

``git`` records the revision (``schema/job/provenance.py``), this interpreter
runs the Whitebox depression removal apart (a lost thread race ends its caller),
and ``uname -p`` comes from ``platform.platform()``. A ``curl`` lands here by name.
"""

SCRIPTS_THE_INTERPRETER_CHILD_RUNS = ("depression_child.py",)
"""It imports ``json``, ``sys`` and ``whitebox_workflows``. A ``python -m pip`` lands here."""


def _is_local(value: object) -> bool:
    """True when *value* names this machine in any spelling (``127.0.0.2``, ``2130706433``)."""
    text = str(value).casefold().rstrip(".")
    for parse in (str, lambda one: int(one, 0)):  # a dotted address, or its integer form
        with contextlib.suppress(ValueError):
            return text in LOCAL_NAMES or ipaddress.ip_address(parse(text)).is_loopback
    return False


def test_the_only_hosts_it_contacts_are_the_ones_it_declares(tmp_path):
    """Caught by host name, by literal address, and by the child executable this one cannot patch.

    A sentinel of the harness's own proves each spy is installed. Every served
    capability has a gate of this name: ``tests/unit/schema/test_capability_egress_gates.py``.
    """
    spies = """
        import contextlib, socket, subprocess, sys
        names, addrs, spawned = [], [], []
        real_addrinfo, real_connect = socket.getaddrinfo, socket.socket.connect
        real_popen = subprocess.Popen.__init__
        def spy_addrinfo(host, port, *a, **k):
            names.append([host, port])
            return real_addrinfo(host, port, *a, **k)
        def spy_connect(self, address, *a, **k):
            addrs.append(list(address) if isinstance(address, tuple) else [address])
            return real_connect(self, address, *a, **k)
        def spy_popen(self, args, *a, **k):
            spawned.append(args if isinstance(args, str) else list(args))
            return real_popen(self, args, *a, **k)
        socket.getaddrinfo, socket.socket.connect = spy_addrinfo, spy_connect
        subprocess.Popen.__init__ = spy_popen
        socket.getaddrinfo("localhost", 9)  # loopback only: needs no route off the machine
        with socket.socket() as probe, contextlib.suppress(OSError):  # refused is expected
            probe.connect(("127.0.0.1", 9))
        subprocess.run([sys.executable, "-c", ""], capture_output=True)
        sentinel = {"names": list(names), "addrs": list(addrs), "spawned": list(spawned)}
        names.clear(), addrs.clear(), spawned.clear()
        seen = {"sentinel": sentinel, "names": names, "addrs": addrs, "spawned": spawned}
    """

    _, recorded = _run_in_a_child(tmp_path, spies)

    sentinel = recorded["sentinel"]
    assert sentinel["names"] and sentinel["addrs"] and sentinel["spawned"], (
        "a spy caught nothing of the harness's own, so it is not installed"
    )
    # The sentinel reached the local machine by name and by address, so it is
    # also the one case that exercises the locality filter below.
    assert all(_is_local(entry[0]) for entry in sentinel["names"] + sentinel["addrs"]), (
        "the locality filter does not recognise the local machine it was handed"
    )
    declared = set(TERRAIN_DELINEATE.reaches_network)

    def reached(kind: str) -> list[str]:
        # Indexed and not unpacked: an IPv6 address has four members, a unix socket none.
        return sorted({str(one[0]) for one in recorded[kind] if not _is_local(one[0])} - declared)

    assert not reached("names"), f"it resolves {reached('names')}, which it does not declare"
    # A connection to a literal address resolves nothing, so it is read apart.
    assert not reached("addrs"), f"it connects to {reached('addrs')}, which it does not declare"
    # A child fetches in an interpreter this one never patched: the children are the measured ones.
    children = sorted({Path(a[0] if isinstance(a, list) else a).name for a in recorded["spawned"]})
    assert children == sorted(CHILD_PROCESSES_THE_JOB_SPAWNS), (
        f"it spawns {children}, and only {sorted(CHILD_PROCESSES_THE_JOB_SPAWNS)} is accounted for"
    )
    # The script is the first argument that is not an option of the interpreter.
    interpreter = Path(sys.executable).name
    by_interpreter = [a for a in recorded["spawned"] if isinstance(a, list) and Path(a[0]).name == interpreter]  # fmt: skip
    scripts = sorted({Path(next((one for one in a[1:] if not one.startswith("-")), "")).name for a in by_interpreter})  # fmt: skip
    assert scripts == sorted(SCRIPTS_THE_INTERPRETER_CHILD_RUNS), (
        f"its interpreter child runs {scripts}, and only "
        f"{sorted(SCRIPTS_THE_INTERPRETER_CHILD_RUNS)} is accounted for"
    )


def test_the_job_runs_on_the_engine_the_request_names(tmp_path):
    """``numpy_d8``, named in ``request.json`` alone, seals with ``fill``, the one method it serves.

    The engines are substitutable, not equivalent, so no area is compared with Whitebox's.
    """
    inputs = {"engine": "numpy_d8", "dem_correction_type": "fill"}
    job, outcome = _run(tmp_path, _request(inputs=inputs), name="numpy_job")

    assert outcome.status == "successful", outcome.errors
    assert job.is_sealed and verify_job(job).ok
    assert read_document(job.provenance_path)["backend"]["name"] == "numpy_d8"
