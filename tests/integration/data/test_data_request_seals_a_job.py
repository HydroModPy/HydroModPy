"""``data-request`` invoked the way an orchestrator invokes it.

One directory in, one seal out. The directory is read the way a stranger reads
it -- with ``geopandas``, ``pandas`` and ``json``, never through the objects
that wrote it.

The provider of the source under test is replaced by a recorder that returns a
canned payload: what these tests hold is the job's own plumbing. The two tests
that run the capability in a subprocess stub nothing they measure: the
confinement gate reads what the job created on the filesystem, and the egress
gate what it resolved on a socket, the real provider included.
"""

from __future__ import annotations

import ipaddress
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import ClassVar

import pytest

from hydromodpy.cli.helpers import (
    EXIT_CONFIG,
    EXIT_NOT_FOUND,
    EXIT_USAGE,
    EXIT_VALIDATION,
    exit_code_for,
)
from hydromodpy.core.exceptions import JobUsageError
from hydromodpy.data.request.artefacts import FEATURES_LAYER
from hydromodpy.data.request.job import DATA_REQUEST, REPORT_PATH, run
from hydromodpy.schema.job import JobDirectory, read_document, verify_job
from hydromodpy.schema.job.layout import ALLOWED_JOB_ENTRIES
from tests._helpers.process_spies import WRITE_SPIES

gpd = pytest.importorskip("geopandas")
pd = pytest.importorskip("pandas")

CALLER_BOX = {"bbox": [-1.85, 48.05, -1.55, 48.25], "crs": "EPSG:4326"}
NETWORK = {"hydrography": {"sources": [{"source": "bdtopage"}]}}
HYDROMETRY = {"hydrometry": {"sources": [{"source": "hubeau"}]}}
PERIOD = {"start": "2020-01-01", "end": "2020-01-31"}


def _request(data: dict | None = None, **inputs: object) -> dict:
    payload: dict[str, object] = {"data": data or NETWORK, "extent": dict(CALLER_BOX)}
    payload.update(inputs)
    return {"process": {"id": "data-request", "version": "1.0.0"}, "inputs": payload}


def _staged(tmp_path: Path, document: dict, *, name: str = "job") -> JobDirectory:
    job = JobDirectory.create(tmp_path / name)
    job.request_path.write_text(json.dumps(document), encoding="utf-8")
    return job


def _network(rows: int = 2):
    from shapely.geometry import LineString

    return gpd.GeoDataFrame(
        {"name": [f"stream-{index}" for index in range(rows)]},
        geometry=[LineString([(-1.8, 48.1), (-1.7 + 0.01 * index, 48.2)]) for index in range(rows)],
        crs="EPSG:4326",
    )


def _stations():
    from datetime import datetime

    from hydromodpy.data.contracts.location import StationLocation
    from hydromodpy.data.contracts.timeseries import PointRecord

    frame = pd.DataFrame(
        {"datetime": pd.date_range("2020-01-01", periods=3, freq="D"), "value": [1.0, 2.0, 3.0]}
    )
    return [
        PointRecord(
            station_id="J0001",
            variable="hydrometry",
            source="hubeau",
            unit="m3/s",
            frequency="D",
            data=frame,
            date_start=datetime(2020, 1, 1),
            date_end=datetime(2020, 1, 3),
            location=StationLocation(id="J0001", x=-1.7, y=48.1, crs="EPSG:4326"),
        )
    ]


@pytest.fixture
def stub_bdtopage(monkeypatch):
    """Replace the WFS walker with a recorder that returns a canned frame."""
    import hydromodpy.data.variables.hydrography.apis.bdtopage as provider

    calls: list[dict] = []
    payload = {"frame": _network()}

    def _record(typename, bbox, *, page_size):
        calls.append({"typename": typename, "bbox": bbox, "page_size": page_size})
        return payload["frame"]

    monkeypatch.setattr(provider, "fetch_projected", _record)
    return calls, payload


@pytest.fixture
def stub_hubeau(monkeypatch):
    from hydromodpy.data.variables.hydrometry.manager import HydrometryManager

    calls: list[dict] = []

    def _record(cfg, *, bbox, station_ids, start, end, context):
        calls.append({"station_ids": station_ids, "start": start, "end": end})
        return _stations()

    monkeypatch.setitem(HydrometryManager.SOURCES, "hubeau", _record)
    return calls


@pytest.fixture
def sealed_network(tmp_path, stub_bdtopage):
    job = _staged(tmp_path, _request())
    outcome = run(job, exit_code_for=exit_code_for)
    assert outcome.status == "successful", outcome.errors
    return job, outcome


def _mask(path: Path) -> Path:
    from shapely.geometry import box

    frame = gpd.GeoDataFrame(
        {"site_id": ["valley"]}, geometry=[box(345000, 6785000, 355000, 6795000)], crs="EPSG:2154"
    )
    frame.to_file(path, driver="GPKG", layer="watershed")
    return path


# --------------------------------------------------------------------------- #
# The seal, and what a stranger finds in the directory
# --------------------------------------------------------------------------- #


def test_a_job_that_finished_is_sealed_and_verifies_against_its_own_seal(sealed_network):
    job, _ = sealed_network
    assert job.is_sealed
    assert verify_job(job).ok


def test_the_directory_carries_only_the_names_the_layout_allows(sealed_network):
    job, _ = sealed_network
    assert {entry.name for entry in job.root.iterdir()} <= ALLOWED_JOB_ENTRIES


def test_outputs_holds_the_report_and_one_file_per_variable_and_source(sealed_network):
    job, _ = sealed_network
    assert sorted(entry.name for entry in job.outputs_dir.iterdir()) == [
        "hydrography_bdtopage.gpkg",
        "request.json",
    ]


def test_the_seal_inventories_every_file_the_report_lists(sealed_network):
    job, outcome = sealed_network
    manifest = read_document(job.manifest_path)
    sealed = {entry["path"]: entry["sha256"] for entry in manifest["artifacts"]}
    report = read_document(job.resolve_output(REPORT_PATH))
    for item in report["files"]:
        assert sealed[f"outputs/{item['path']}"] == item["sha256"]
    assert manifest["job_id"] == outcome.job_id


def test_a_stranger_opens_the_network_with_geopandas_alone(sealed_network):
    job, _ = sealed_network
    frame = gpd.read_file(job.outputs_dir / "hydrography_bdtopage.gpkg", layer=FEATURES_LAYER)
    assert len(frame) == 2


def test_a_stranger_opens_the_chronicles_with_pandas_alone(tmp_path, stub_hubeau):
    job = _staged(
        tmp_path,
        _request(HYDROMETRY, extent={"station_ids": ["J0001"]}, period=dict(PERIOD)),
    )
    outcome = run(job, exit_code_for=exit_code_for)

    assert outcome.status == "successful", outcome.errors
    table = pd.read_parquet(job.outputs_dir / "hydrometry_hubeau.parquet")
    assert list(table["station_id"].unique()) == ["J0001"]
    assert stub_hubeau[0]["station_ids"] == ["J0001"]


def test_an_empty_answer_is_a_success_that_seals_the_report_and_no_data(tmp_path, stub_bdtopage):
    _, payload = stub_bdtopage
    payload["frame"] = _network(0)
    job = _staged(tmp_path, _request())

    outcome = run(job, exit_code_for=exit_code_for)

    assert outcome.status == "successful", outcome.errors
    assert verify_job(job).ok
    assert [entry.name for entry in job.outputs_dir.iterdir()] == ["request.json"]
    assert read_document(job.resolve_output(REPORT_PATH))["files"][0]["empty"] is True


# --------------------------------------------------------------------------- #
# Refusals: nothing is written but the outcome
# --------------------------------------------------------------------------- #


def _untouched(job: JobDirectory) -> bool:
    return {entry.name for entry in job.root.iterdir()} == {"request.json", "outcome.json"}


def test_a_custom_source_is_refused_before_the_job_is_touched(tmp_path):
    data = {"dem": {"sources": [{"source": "custom", "path": str(tmp_path / "dem.tif")}]}}
    (tmp_path / "dem.tif").write_bytes(b"")
    job = _staged(tmp_path, _request(data))

    outcome = run(job, exit_code_for=exit_code_for)

    assert outcome.exit_code == EXIT_CONFIG
    assert "custom" in json.dumps(outcome.errors)
    assert _untouched(job)


def test_a_request_the_model_refuses_never_reaches_a_provider(tmp_path, stub_bdtopage):
    calls, _ = stub_bdtopage
    job = _staged(tmp_path, _request(extent={"bbox": [1, 1, 0, 0], "crs": "EPSG:4326"}))

    outcome = run(job, exit_code_for=exit_code_for)

    assert outcome.exit_code == EXIT_CONFIG
    assert calls == []
    assert _untouched(job)


def test_a_mask_that_is_not_there_is_refused_as_not_found(tmp_path, stub_bdtopage):
    job = _staged(tmp_path, _request(extent={"mask": {"href": str(tmp_path / "absent.gpkg")}}))

    outcome = run(job, exit_code_for=exit_code_for)

    assert outcome.exit_code == EXIT_NOT_FOUND
    assert _untouched(job)


def test_a_mask_whose_bytes_are_not_the_pinned_ones_is_refused(tmp_path, stub_bdtopage):
    mask = _mask(tmp_path / "watershed.gpkg")
    job = _staged(tmp_path, _request(extent={"mask": {"href": str(mask), "sha256": "0" * 64}}))

    outcome = run(job, exit_code_for=exit_code_for)

    assert outcome.status == "failed"
    assert "pinned" in json.dumps(outcome.errors)
    assert _untouched(job)


def test_a_mask_that_is_not_a_vector_file_is_refused_as_bad_input(tmp_path, stub_bdtopage):
    bogus = tmp_path / "watershed.gpkg"
    bogus.write_text("not a vector", encoding="utf-8")
    job = _staged(tmp_path, _request(extent={"mask": {"href": str(bogus)}}))

    outcome = run(job, exit_code_for=exit_code_for)

    assert outcome.exit_code == EXIT_VALIDATION
    assert _untouched(job)


def test_a_request_for_another_capability_is_refused(tmp_path, stub_bdtopage):
    document = _request()
    document["process"] = {"id": "terrain-delineate", "version": "1.1.0"}
    job = _staged(tmp_path, document)

    outcome = run(job, exit_code_for=exit_code_for)

    assert outcome.status == "failed"
    assert _untouched(job)


def test_an_unknown_capability_id_is_an_invocation_error() -> None:
    from hydromodpy.cli._workers.process import capability

    with pytest.raises(JobUsageError) as caught:
        capability("data-requests")
    assert exit_code_for(caught.value) == EXIT_USAGE


# --------------------------------------------------------------------------- #
# The mask, the job id and reuse
# --------------------------------------------------------------------------- #


def test_a_mask_is_the_extent_and_reaches_the_provider_reprojected(tmp_path, stub_bdtopage):
    calls, _ = stub_bdtopage
    mask = _mask(tmp_path / "watershed.gpkg")
    job = _staged(tmp_path, _request(extent={"mask": {"href": str(mask)}}))

    outcome = run(job, exit_code_for=exit_code_for)

    assert outcome.status == "successful", outcome.errors
    xmin, ymin, xmax, ymax = calls[0]["bbox"]
    assert 250_000 < xmin < xmax < 450_000 and 6_700_000 < ymin < ymax < 6_900_000, (
        "BD Topage is asked in Lambert-93"
    )


def test_the_input_set_records_the_mask_by_its_digest(tmp_path, stub_bdtopage):
    from hydromodpy.schema.job.digest import sha256_file

    mask = _mask(tmp_path / "watershed.gpkg")
    job = _staged(tmp_path, _request(extent={"mask": {"href": str(mask)}}))
    run(job, exit_code_for=exit_code_for)

    inputset = read_document(job.inputset_path)
    (resource,) = [item for item in inputset["resources"] if item["name"] == "mask"]
    assert resource["sha256"] == sha256_file(mask)[0]
    assert resource["spatial"]["crs"] == "EPSG:2154"
    (question,) = [item for item in inputset["resources"] if item["name"] == "request"]
    assert "mask" not in json.dumps(question), "the mask is recorded once, as its own resource"


def test_one_mask_under_two_names_is_one_job(tmp_path, stub_bdtopage):
    first = _mask(tmp_path / "a.gpkg")
    second = tmp_path / "b.gpkg"
    second.write_bytes(first.read_bytes())

    one = run(
        _staged(tmp_path, _request(extent={"mask": {"href": str(first)}}), name="one"),
        exit_code_for=exit_code_for,
    )
    two = run(
        _staged(tmp_path, _request(extent={"mask": {"href": str(second)}}), name="two"),
        exit_code_for=exit_code_for,
    )

    assert one.job_id == two.job_id


def test_a_sealed_directory_under_the_same_id_is_re_reported_and_not_re_run(
    sealed_network, stub_bdtopage
):
    job, outcome = sealed_network
    calls, _ = stub_bdtopage
    before = len(calls)

    again = run(job, exit_code_for=exit_code_for)

    assert again.reused and again.job_id == outcome.job_id
    assert len(calls) == before


def test_a_sealed_directory_under_another_id_is_refused(sealed_network):
    job, _ = sealed_network
    job.request_path.write_text(
        json.dumps(_request(extent={"bbox": [-1.8, 48.0, -1.6, 48.2], "crs": "EPSG:4326"})),
        encoding="utf-8",
    )

    with pytest.raises(JobUsageError):
        run(job, exit_code_for=exit_code_for)


def test_a_failed_variable_fails_the_job_with_a_typed_code_and_no_seal(tmp_path, monkeypatch):
    from hydromodpy.core.exceptions import DataSourceError
    from hydromodpy.data.variables.hydrometry.manager import HydrometryManager

    def _down(cfg, **kwargs):
        raise DataSourceError("provider down")

    monkeypatch.setitem(HydrometryManager.SOURCES, "hubeau", _down)
    job = _staged(
        tmp_path,
        _request(HYDROMETRY, extent={"station_ids": ["J0001"]}, period=dict(PERIOD)),
    )

    outcome = run(job, exit_code_for=exit_code_for)

    assert outcome.status == "failed"
    assert outcome.exit_code == exit_code_for(DataSourceError("x"))
    assert not job.is_sealed
    assert read_document(job.resolve_output(REPORT_PATH))["failures"]


# --------------------------------------------------------------------------- #
# A plugin source asked by name
# --------------------------------------------------------------------------- #


class AcmeLineworkSource:
    """A river-network source a third party ships, named in no file of this tree."""

    source_id: ClassVar[str] = "acme-linework"
    payload_kind: ClassVar[str] = "features"
    extent_crs: ClassVar[str] = "EPSG:3035"
    selectors: ClassVar[tuple[str, ...]] = ("extent",)
    period_need: ClassVar[str] = "refused"
    hosts: ClassVar[tuple[str, ...]] = ("linework.acme.example",)
    writes_out_dir: ClassVar[bool] = False

    def __init__(self, *, reaches: int = 2) -> None:
        self.reaches = reaches
        self.variables: tuple[str, ...] = ("stream_network",)

    def fetch(self, request):
        from hydromodpy.data.source.port import FetchResult, extent_for

        return FetchResult(
            source_id=self.source_id,
            kind=self.payload_kind,
            variables=self.variables,
            extent=extent_for(self, request),
            features=_network(self.reaches),
        )


def test_a_request_names_an_installed_source_and_the_job_seals(tmp_path, isolated_registry):
    isolated_registry.register(AcmeLineworkSource)
    document = _request()
    del document["inputs"]["data"]
    document["inputs"]["installed"] = [{"name": "acme-linework", "options": {"reaches": 3}}]
    job = _staged(tmp_path, document)

    outcome = run(job, exit_code_for=exit_code_for)

    assert outcome.status == "successful", outcome.errors
    assert verify_job(job).ok
    frame = gpd.read_file(job.outputs_dir / "installed_acme-linework.gpkg", layer=FEATURES_LAYER)
    assert len(frame) == 3


def test_a_request_naming_an_absent_source_is_refused_with_the_directory_untouched(tmp_path):
    document = _request()
    document["inputs"]["installed"] = [{"name": "acme-linework"}]
    job = _staged(tmp_path, document)

    outcome = run(job, exit_code_for=exit_code_for)

    assert outcome.exit_code == EXIT_CONFIG
    assert "acme-linework" in json.dumps(outcome.errors)
    assert _untouched(job)


# --------------------------------------------------------------------------- #
# The two gates that run the job in a subprocess
# --------------------------------------------------------------------------- #

_STUB_PROVIDER = (
    "import hydromodpy.data.variables.hydrography.apis.bdtopage as provider\n"
    "import geopandas as gpd\n"
    "from shapely.geometry import LineString\n"
    "provider.fetch_projected = lambda typename, bbox, *, page_size: gpd.GeoDataFrame(\n"
    "    {'name': ['a']},\n"
    "    geometry=[LineString([(-1.8, 48.1), (-1.7, 48.2)])],\n"
    "    crs='EPSG:4326',\n"
    ")\n"
)


@pytest.mark.allow_subprocess
def test_it_writes_nowhere_but_the_job_directory_and_the_tmpdir_it_declares(tmp_path):
    """The declaration is a promise an orchestrator mounts the filesystem on.

    The spies record every Python-level creation, and ``HOME`` points at an
    empty directory that must still be empty afterwards: the job registers
    nothing in the user's state directory and fills no user cache.
    """
    scratch = tmp_path / "tmp"
    scratch.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    created = tmp_path / "created.json"
    job = _staged(tmp_path, _request())

    script = (
        WRITE_SPIES
        + "import json, sys\n"
        + _STUB_PROVIDER
        + "from hydromodpy.cli.helpers import exit_code_for\n"
        "from hydromodpy.schema.job import JobDirectory\n"
        "from hydromodpy.data.request.job import run\n"
        "try:\n"
        "    outcome = run(JobDirectory.open(sys.argv[1]), exit_code_for=exit_code_for)\n"
        "finally:\n"
        "    real_bopen(sys.argv[2], 'w').write(json.dumps(seen))\n"
        "sys.exit(outcome.exit_code)\n"
    )
    env = dict(os.environ, TMPDIR=str(scratch), HOME=str(home), HMP_NO_PROGRESS="1")
    env.pop("XDG_CACHE_HOME", None)
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
    known = {"$TMPDIR": scratch.resolve()}
    unknown = set(DATA_REQUEST.writes_outside_jobdir) - set(known)
    assert not unknown, f"this test cannot point at the declared location(s) {sorted(unknown)}"
    allowed = [job.root.resolve()] + [known[name] for name in DATA_REQUEST.writes_outside_jobdir]
    paths = [path for path in paths if path != Path(os.devnull)]
    outside = [path for path in paths if not any(path.is_relative_to(root) for root in allowed)]
    assert not outside, f"it writes into {outside}, which it does not declare"
    assert any(path.is_relative_to(scratch.resolve()) for path in paths), (
        "nothing landed under TMPDIR, so declaring it over-claims"
    )
    assert list(scratch.iterdir()) == [], "the scratch survived the job"
    assert list(home.iterdir()) == [], "it left something in the user's home directory"


LOCAL_NAMES = frozenset({"localhost", "localhost.localdomain", "ip6-localhost"})
"""Names of the local machine. Not egress: reachable with no route out at all."""

CHILD_PROCESSES_THE_JOB_SPAWNS = ("git", "uname")
"""The executables the job runs: ``git`` for the provenance, ``uname -p`` for
``platform.platform()``. A job that shelled out to ``curl`` would land here by name."""


def _is_local(value: object) -> bool:
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


@pytest.mark.allow_subprocess
def test_the_only_hosts_it_contacts_are_the_ones_it_declares(tmp_path):
    """Nothing is stubbed here, and the run is allowed to fail.

    Offline, the spy records the name before ``getaddrinfo`` raises, which is
    the observation the gate needs. Three angles: a host resolved by name, a
    connection opened to a literal address, and a child process.
    """
    seen = tmp_path / "seen.json"
    job = _staged(
        tmp_path,
        _request(
            {"hydrography": {"sources": [{"source": "bdtopage", "page_size": 1}]}},
            extent={"bbox": [-1.681, 48.111, -1.679, 48.113], "crs": "EPSG:4326"},
        ),
    )

    script = (
        "import json, socket, subprocess, sys\n"
        "names, addrs, spawned = [], [], []\n"
        "real_addrinfo, real_connect = socket.getaddrinfo, socket.socket.connect\n"
        "real_popen = subprocess.Popen.__init__\n"
        "def spy_addrinfo(host, port, *a, **k):\n"
        "    record = [host, port, []]\n"
        "    names.append(record)\n"
        "    answer = real_addrinfo(host, port, *a, **k)\n"
        "    record[2] = sorted({str(entry[4][0]) for entry in answer})\n"
        "    return answer\n"
        "def spy_connect(self, address, *a, **k):\n"
        "    addrs.append(list(address) if isinstance(address, tuple) else [address])\n"
        "    return real_connect(self, address, *a, **k)\n"
        "def spy_popen(self, args, *a, **k):\n"
        "    spawned.append(args if isinstance(args, str) else list(args))\n"
        "    return real_popen(self, args, *a, **k)\n"
        "socket.getaddrinfo, socket.socket.connect = spy_addrinfo, spy_connect\n"
        "subprocess.Popen.__init__ = spy_popen\n"
        "socket.getaddrinfo('localhost', 9)\n"
        "probe = socket.socket()\n"
        "try:\n"
        "    probe.connect(('127.0.0.1', 9))\n"
        "except OSError:\n"
        "    pass\n"
        "finally:\n"
        "    probe.close()\n"
        "subprocess.run([sys.executable, '-c', ''], capture_output=True)\n"
        "sentinel = {'names': list(names), 'addrs': list(addrs), 'spawned': list(spawned)}\n"
        "names.clear()\n"
        "addrs.clear()\n"
        "spawned.clear()\n"
        "from hydromodpy.cli.helpers import exit_code_for\n"
        "from hydromodpy.schema.job import JobDirectory\n"
        "from hydromodpy.data.request.job import run\n"
        "outcome = run(JobDirectory.open(sys.argv[1]), exit_code_for=exit_code_for)\n"
        "open(sys.argv[2], 'w').write(json.dumps({'sentinel': sentinel, 'names': names,\n"
        "    'addrs': addrs, 'spawned': spawned, 'status': outcome.status}))\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", script, str(job.root), str(seen)],
        env=dict(os.environ, HMP_NO_PROGRESS="1"),
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )

    assert seen.is_file(), completed.stderr[-4000:]
    recorded = json.loads(seen.read_text(encoding="utf-8"))
    sentinel = recorded["sentinel"]
    assert sentinel["names"] and sentinel["addrs"] and sentinel["spawned"], (
        "a spy caught nothing of the harness's own, so it is not installed"
    )
    assert all(_is_local(entry[0]) for entry in sentinel["names"] + sentinel["addrs"])

    declared = set(DATA_REQUEST.reaches_network)
    reached = {str(entry[0]) for entry in recorded["names"] if not _is_local(entry[0])}
    assert reached, "the job resolved no name at all, so this gate proved nothing"
    assert not sorted(reached - declared), f"it resolves {sorted(reached - declared)}, undeclared"
    from_declared = {
        address for entry in recorded["names"] if str(entry[0]) in declared for address in entry[2]
    }
    egress = sorted(
        {str(entry[0]) for entry in recorded["addrs"] if not _is_local(entry[0])}
        - declared
        - from_declared
    )
    assert not egress, f"it connects to {egress}, which it does not declare"
    children = sorted(
        {Path(argv[0] if isinstance(argv, list) else argv).name for argv in recorded["spawned"]}
    )
    assert children == sorted(CHILD_PROCESSES_THE_JOB_SPAWNS), (
        f"it spawns {children}, and only {sorted(CHILD_PROCESSES_THE_JOB_SPAWNS)} is accounted for"
    )
