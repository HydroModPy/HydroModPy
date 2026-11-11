"""``domain-build`` invoked the way an orchestrator invokes it, one directory in, one seal out.

The directory is read the way a stranger would, with ``rasterio``, ``geopandas`` and ``json``.
The terrain is a synthetic tilted plane of 20 x 20 cells of 25 m with a 2 x 2 nodata hole inside
the mask, so the sentinel and the mask meet on one run, and no fork-unsafe engine is needed.
"""

from __future__ import annotations

import contextlib
import ipaddress
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

from hydromodpy.catchment.algorithms.surface_from_dem import build_surface_topo_from_dem
from hydromodpy.cli.exit_codes import EXIT_CONFIG, EXIT_NOT_FOUND, EXIT_VALIDATION, exit_code_for
from hydromodpy.core.exceptions import JobUsageError
from hydromodpy.core.io.file_digest import sha256_and_size
from hydromodpy.model.domain import worker
from hydromodpy.model.domain.build import build_domain
from hydromodpy.model.domain.capability import (
    ACTIVE_CELLS_PATH,
    BOTTOM_PATH,
    DOMAIN_BUILD,
    DOMAIN_DOCUMENT_PATH,
    THICKNESS_PATH,
    DomainBuildRequest,
)
from hydromodpy.model.domain.domain_config import DomainConfig
from hydromodpy.model.domain.worker import run
from hydromodpy.schema.job.directory import JobDirectory
from hydromodpy.schema.job.documents import read_document
from hydromodpy.schema.job.layout import ALLOWED_JOB_ENTRIES
from hydromodpy.schema.job.request import content_address
from hydromodpy.schema.job.seal import verify_job
from tests._helpers.domain_cases import write_mask
from tests._helpers.geotiffs import write_geotiff
from tests._helpers.process_spies import WRITE_SPIES

gpd = pytest.importorskip("geopandas")
rasterio = pytest.importorskip("rasterio")
from shapely.geometry import LineString, box  # after the skip: shapely comes with geopandas

CRS, CELL, SIZE, XMIN, YMAX, NODATA = "EPSG:2154", 25.0, 20, 300000.0, 6700500.0, -9999.0
NODATA_ROWS = NODATA_COLS = slice(5, 7)  # a 2 x 2 hole inside the mask
MASK_BOX = (300100.0, 6700100.0, 300400.0, 6700400.0)
ELSEWHERE = (400000.0, 6800000.0, 400100.0, 6800100.0)
CELLS_UNDER_MASK = 144  # 12 x 12 cell centers fall inside the box
ACTIVE_CELLS = CELLS_UNDER_MASK - 4  # the four nodata cells are not part of the domain
THICKNESS = 30.0
FLAT = {"kind": "flat_substratum", "substratum_elevation": 60.0}
POINTER = '"pointer": "/inputs/{}"'


def _elevation() -> np.ndarray:
    rows, cols = np.indices((SIZE, SIZE))
    return 100.0 + 0.5 * cols + 0.25 * rows


def _raster(path: Path, values: np.ndarray, *, crs: str | None = CRS) -> Path:
    return write_geotiff(path, values, origin=(XMIN, YMAX), cell=CELL, crs=crs, nodata=NODATA)


def _dem(path: Path, *, crs: str | None = CRS) -> Path:
    values = _elevation()
    values[NODATA_ROWS, NODATA_COLS] = NODATA
    return _raster(path, values, crs=crs)


def _request(tmp_path: Path, **overrides: object) -> dict:
    inputs: dict[str, object] = {
        "dem": {"href": str(_dem(tmp_path / "dem.tif")), "type": "image/tiff; application=geotiff"},
        "depth_model": {"kind": "constant_thickness", "thickness": THICKNESS},
        "mask": {"href": str(write_mask(tmp_path / "mask.gpkg", {"watershed": MASK_BOX}))},
    }
    inputs.update(overrides.pop("inputs", {}))  # type: ignore[arg-type]
    return {"process": {"id": "domain-build", "version": "1.0.0"}, "inputs": inputs, **overrides}


def _staged(tmp_path: Path, document: dict, *, name: str = "job") -> JobDirectory:
    job = JobDirectory.create(tmp_path / name)
    job.request_path.write_text(json.dumps(document), encoding="utf-8")
    return job


def _band(job: JobDirectory, relative: str) -> np.ndarray:
    with rasterio.open(str(job.resolve_output(relative))) as source:
        return source.read(1)


def _succeeds(tmp_path: Path, **inputs: object):
    job = _staged(tmp_path, _request(tmp_path, inputs=inputs))
    outcome = run(job, exit_code_for=exit_code_for)
    assert outcome.status == "successful", outcome.errors
    return job, outcome


@pytest.fixture
def sealed_job(tmp_path):
    return _succeeds(tmp_path)


def test_a_finished_job_is_sealed_with_the_declared_rasters_on_the_terrain_grid_and_nan_outside_the_domain(sealed_job):  # fmt: skip
    job, outcome = sealed_job
    declared = {o.path.removeprefix("outputs/") for o in DOMAIN_BUILD.outputs if o.path.startswith("outputs/")}  # fmt: skip

    assert job.is_sealed and verify_job(job).ok
    assert {entry.name for entry in job.root.iterdir()} <= ALLOWED_JOB_ENTRIES
    assert {entry.name for entry in job.outputs_dir.iterdir()} == declared
    assert read_document(job.manifest_path)["request_id"] == outcome.job_id
    assert read_document(job.outcome_path)["job_id"] == outcome.job_id
    assert outcome.job_id.startswith("sha256:")
    # The mask says which cells are active, never which exist. The DEM sentinel is no safe nodata
    # for the elevations: ``flat_like`` clamps it, so NaN is written and declared.
    inactive = ~_band(job, ACTIVE_CELLS_PATH).astype(bool)

    with rasterio.open(str(job.root.parent / "dem.tif")) as terrain:
        reference = (terrain.shape, terrain.transform, terrain.crs)
    for relative in (BOTTOM_PATH, THICKNESS_PATH, ACTIVE_CELLS_PATH):
        with rasterio.open(str(job.resolve_output(relative))) as produced:
            assert (produced.shape, produced.transform, produced.crs) == reference, relative
            if relative != ACTIVE_CELLS_PATH:
                assert np.isnan(produced.nodata), relative
                assert np.isnan(produced.read(1)[inactive]).all(), relative
    # Both exclusions are present, so neither is asserted vacuously.
    assert inactive[NODATA_ROWS, NODATA_COLS].all() and inactive[0, 0]
    # The bottom is the runtime geometry: a body reimplementing it would seal an unrelated artifact.
    active = ~inactive
    runtime = build_domain(DomainConfig.with_thickness(THICKNESS), surface_topo=build_surface_topo_from_dem(job.root.parent / "dem.tif"))  # fmt: skip

    np.testing.assert_allclose(_band(job, BOTTOM_PATH)[active], _elevation()[active] - THICKNESS)
    np.testing.assert_array_equal(_band(job, BOTTOM_PATH)[active], runtime.substratum.as_array()[active])  # fmt: skip
    np.testing.assert_allclose(_band(job, THICKNESS_PATH)[active], THICKNESS)


def test_the_document_counts_the_active_cells_names_the_terrain_digest_and_keeps_the_job_id(sealed_job):  # fmt: skip
    """A mean over the whole grid would average the sentinel in. The top is named by digest."""
    job, outcome = sealed_job
    document = read_document(job.resolve_output(DOMAIN_DOCUMENT_PATH))
    active = _band(job, ACTIVE_CELLS_PATH).astype(bool)

    assert int(active.sum()) == ACTIVE_CELLS
    assert (document["active_cells"]["count"], document["active_cells"]["total"]) == (ACTIVE_CELLS, SIZE * SIZE)  # fmt: skip
    assert document["active_cells"]["area_m2"] == pytest.approx(ACTIVE_CELLS * CELL * CELL)
    assert document["statistics"]["over"] == "active_cells"
    assert document["statistics"]["top"]["mean"] == pytest.approx(float(_elevation()[active].mean()))  # fmt: skip
    assert document["statistics"]["top"]["min"] > NODATA
    top = {"input": "dem", "sha256": sha256_and_size(job.root.parent / "dem.tif")[0]}
    assert (document["layers"][0]["top"], document["layers"][0]["bottom"]) == (top, BOTTOM_PATH)
    assert document["crs"] == CRS
    # A request without a substratum keeps the job id it had before the member existed.
    inputs = read_document(job.request_path)["inputs"]
    payload = DomainBuildRequest.model_validate(inputs).model_dump(mode="json")
    payload.pop("substratum")
    payload["dem"] = {"sha256": sha256_and_size(Path(inputs["dem"]["href"]))[0]}
    payload["mask"] = {"sha256": sha256_and_size(Path(inputs["mask"]["href"]))[0]}
    payload["mask_layer"] = "watershed"
    assert outcome.job_id == content_address(process_id=DOMAIN_BUILD.id, process_version=DOMAIN_BUILD.version, inputs=payload)  # fmt: skip


def test_a_flat_substratum_puts_the_bottom_at_its_elevation_and_none_at_a_nodata_cell(tmp_path):
    """``flat_like`` clamps ``-9999`` to ``-10000``: the raster once declared one and held the other."""
    job, _ = _succeeds(tmp_path, depth_model=FLAT)

    bottom = _band(job, BOTTOM_PATH)
    np.testing.assert_allclose(bottom[_band(job, ACTIVE_CELLS_PATH).astype(bool)], 60.0)
    assert np.isnan(bottom[NODATA_ROWS, NODATA_COLS]).all()
    assert not (bottom == -10000.0).any()
    assert read_document(job.resolve_output(DOMAIN_DOCUMENT_PATH))["depth_model"] == FLAT
    # The clamp is still there one layer down, so this test guards a live mechanism.
    runtime = build_domain({"depth_model": FLAT}, surface_topo=build_surface_topo_from_dem(job.root.parent / "dem.tif"))  # fmt: skip
    assert (runtime.substratum.as_array()[NODATA_ROWS, NODATA_COLS] == -10000.0).all()


def _plain(t: Path) -> dict:
    plain = write_geotiff(t / "plain.tif", _elevation(), origin=(XMIN, YMAX), cell=CELL)
    return {"dem": {"href": str(plain), "sha256": sha256_and_size(plain)[0].upper()}}


def _lonlat(t: Path) -> dict:
    gpd.GeoDataFrame(geometry=[box(*MASK_BOX)], crs=CRS).to_crs("EPSG:4326").to_file(str(t / "lonlat.gpkg"), layer="watershed")  # fmt: skip
    return {"mask": {"href": str(t / "lonlat.gpkg")}}


@pytest.mark.parametrize(
    ("inputs", "active"),
    [
        (lambda t: {"mask": None}, SIZE * SIZE - 4),
        (_plain, CELLS_UNDER_MASK),
        (lambda t: {"mask": {"href": str(write_mask(t / "two.gpkg", {"inside": MASK_BOX, "outside": ELSEWHERE}))}, "mask_layer": "inside"}, ACTIVE_CELLS),
        (_lonlat, ACTIVE_CELLS),
    ],
    ids=["no_mask_every_cell_carrying_data", "terrain_without_nodata_pinned_by_its_digest_mask_alone_decides", "the_named_layer_is_read", "mask_in_another_crs"],
)  # fmt: skip
def test_the_active_cells_are_the_terrain_cells_carrying_data_under_the_mask(tmp_path, inputs, active):  # fmt: skip
    given = inputs(tmp_path)
    job, _ = _succeeds(tmp_path, **given)

    assert int(_band(job, ACTIVE_CELLS_PATH).sum()) == active
    if given.get("mask", "") is None:
        assert read_document(job.resolve_output(DOMAIN_DOCUMENT_PATH))["active_cells"]["mask"] is None  # fmt: skip


def test_a_terrain_of_several_bands_is_read_on_band_one_and_says_so(tmp_path):
    """Accepted, since a DEM as band 1 of a stack is legitimate; warned, since the rest is ignored."""
    stack = np.stack([_elevation(), np.zeros((SIZE, SIZE)), np.zeros((SIZE, SIZE))])
    stacked = write_geotiff(tmp_path / "stacked.tif", stack, origin=(XMIN, YMAX), cell=CELL, nodata=NODATA)  # fmt: skip

    job, outcome = _succeeds(tmp_path, dem={"href": str(stacked)})

    assert any("band 1 is read" in warning for warning in outcome.warnings)
    active = _band(job, ACTIVE_CELLS_PATH).astype(bool)
    np.testing.assert_allclose(_band(job, BOTTOM_PATH)[active], _elevation()[active] - THICKNESS)


def _substratum(t: Path, values: np.ndarray | None, *, crs: str | None = CRS) -> dict:
    inputs: dict[str, object] = {"depth_model": {"kind": "raster_substratum"}}
    if values is not None:
        inputs["substratum"] = {"href": str(_raster(t / "substratum.tif", values, crs=crs))}
    return inputs


@pytest.mark.parametrize(
    "values",
    [_elevation() - 40.0, np.pad(np.full((14, 14), 60.0), 3, constant_values=NODATA)],
    ids=["everywhere", "covering_the_mask_alone_serves_a_masked_terrain"],
)  # fmt: skip
def test_a_raster_substratum_places_the_bottom_and_the_seal_names_its_digest(tmp_path, values):
    """The mask is the extent: cells outside it need no substratum value."""
    job, _ = _succeeds(tmp_path, **_substratum(tmp_path, values))

    assert verify_job(job).ok
    active = _band(job, ACTIVE_CELLS_PATH).astype(bool)
    np.testing.assert_allclose(_band(job, BOTTOM_PATH)[active], values[active])
    digest, _size = sha256_and_size(tmp_path / "substratum.tif")
    layer = read_document(job.resolve_output(DOMAIN_DOCUMENT_PATH))["layers"][0]
    assert layer["substratum"] == {"input": "substratum", "sha256": digest}
    resources = read_document(job.inputset_path)["resources"]
    assert {"name": "substratum", "sha256": digest} in [{"name": r["name"], "sha256": r["sha256"]} for r in resources]  # fmt: skip


def _rotated(t: Path) -> dict:
    """A sheared grid has no ``dx`` nor ``dy`` to publish."""
    from affine import Affine

    with rasterio.open(str(t / "rotated.tif"), "w", driver="GTiff", height=SIZE, width=SIZE, count=1, dtype="float64", crs=CRS,
                       transform=Affine(CELL, 5.0, XMIN, 5.0, -CELL, YMAX), nodata=NODATA) as sink:  # fmt: skip
        sink.write(_elevation(), 1)
    return {"dem": {"href": str(t / "rotated.tif")}, "mask": None}


def _vector(t: Path, name: str, geometry: object, layer: str) -> dict:
    """A mask of *geometry*: a network handed in for a catchment would burn a one-cell sliver."""
    gpd.GeoDataFrame({"name": [name]}, geometry=[geometry], crs=CRS).to_file(str(t / f"{name}.gpkg"), layer=layer)  # fmt: skip
    return {"mask": {"href": str(t / f"{name}.gpkg")}}


def _text(t: Path, name: str) -> str:
    (t / name).write_text("not a dataset", encoding="utf-8")
    return str(t / name)


@pytest.mark.parametrize(
    ("inputs", "request_overrides", "exit_code", "fragments", "untouched"),
    [
        (lambda t: {"dem": {"href": str(_dem(t / "bare.tif", crs=None))}}, {}, EXIT_VALIDATION, ("carries no CRS",), True),
        (lambda t: {"dem": {"href": _text(t, "text.tif")}}, {}, EXIT_VALIDATION, ("cannot be opened as a raster",), True),
        (lambda t: {"dem": {"href": str(t / "dem.tif"), "sha256": "00" * 32}}, {}, EXIT_VALIDATION, ("the bytes are not the ones the job asked for",), True),
        (lambda t: {"dem": {"href": str(t / "absent.tif")}}, {}, EXIT_NOT_FOUND, ('"code": "HMPY.E211"', "absent.tif', and"), True),
        (_rotated, {}, EXIT_VALIDATION, ("rotated or sheared transform",), True),
        (lambda t: {"mask": {"href": str(write_mask(t / "far.gpkg", {"watershed": ELSEWHERE}))}}, {}, EXIT_VALIDATION, ("no cell of the terrain is active",), False),
        (lambda t: {"mask": {"href": str(write_mask(t / "two.gpkg", {"first": MASK_BOX, "second": MASK_BOX}))}}, {}, EXIT_CONFIG, (POINTER.format("mask_layer"),), True),
        (lambda t: {"mask": None, "mask_layer": "watershed"}, {}, EXIT_CONFIG, (POINTER.format("mask_layer"),), True),
        (lambda t: {"mask_layer": "catchment"}, {}, EXIT_CONFIG, ("holds no layer named 'catchment'", POINTER.format("mask_layer")), True),
        (lambda t: {"mask": {"href": _text(t, "text.gpkg")}}, {}, EXIT_VALIDATION, ("cannot be opened as a vector dataset",), True),
        (lambda t: {"mask": {"href": str(write_mask(t / "bare.gpkg", {"watershed": MASK_BOX}, crs=None))}}, {}, EXIT_VALIDATION, ("carries no CRS, so it cannot be placed",), False),
        (lambda t: _vector(t, "nothing", None, "watershed"), {}, EXIT_VALIDATION, ("holds no geometry to bound the domain",), False),
        (lambda t: _vector(t, "talweg", LineString([(300100.0, 6700100.0), (300400.0, 6700400.0)]), "network"), {}, EXIT_VALIDATION, ("holds LineString geometries",), False),
        (lambda t: {"depth_model": {"kind": "flat_substratum", "substratum_elevation": 5000.0}}, {}, EXIT_CONFIG, ('"code": "HMPY.E101"', POINTER.format("depth_model")), False),
        (lambda t: {}, {"outputs": {"mesh": {}}}, EXIT_CONFIG, (), True),
        (lambda t: _substratum(t, np.where(np.indices((SIZE, SIZE))[1] < 10, 60.0, NODATA)), {}, EXIT_VALIDATION, ("without a value",), False),
        (lambda t: _substratum(t, None), {}, EXIT_CONFIG, (POINTER.format("substratum"),), True),
        (lambda t: {"substratum": _substratum(t, _elevation() - 40.0)["substratum"]}, {}, EXIT_CONFIG, (POINTER.format("substratum"),), True),
        (lambda t: _substratum(t, _elevation() - 40.0, crs=None), {}, EXIT_VALIDATION, ("input substratum", "carries no CRS"), True),
    ],
    ids=[
        "terrain_without_crs", "terrain_not_a_raster", "terrain_bytes_not_pinned", "terrain_absent", "terrain_rotated",
        "mask_selects_no_cell", "mask_of_several_layers_naming_none", "layer_named_without_mask", "layer_the_mask_lacks",
        "mask_not_a_vector", "mask_without_crs", "mask_without_geometry", "mask_of_lines", "substratum_above_the_terrain",
        "output_nobody_declares", "raster_missing_active_cells", "raster_kind_without_substratum",
        "substratum_handed_to_another_kind", "substratum_without_crs",
    ],
)  # fmt: skip
def test_a_request_it_cannot_serve_fails_typed_and_unsealed(
    tmp_path, inputs, request_overrides, exit_code, fragments, untouched
):
    """A bad input is the caller's fault: a typed exit code, never the ``HMPY.E000`` of a bug."""
    job = _staged(tmp_path, _request(tmp_path, inputs=inputs(tmp_path), **request_overrides))

    outcome = run(job, exit_code_for=exit_code_for)

    assert (outcome.status, outcome.exit_code) == ("failed", exit_code)
    (error,) = outcome.errors[:1]
    pointers = [detail.get("pointer") for detail in error.get("details") or []]
    for fragment in fragments:
        if fragment.startswith('"pointer"'):
            assert fragment.split('"')[3] in pointers, error
        elif fragment.startswith('"code"'):
            assert error["code"] == fragment.split('"')[3], error
        else:
            assert fragment in error["detail"], error
    assert not job.is_sealed
    assert job.outputs_dir.exists() is not untouched


def test_a_depth_model_that_leaves_no_substratum_is_a_contract_violation(tmp_path, monkeypatch):
    monkeypatch.setattr(worker, "build_domain", lambda *a, **k: SimpleNamespace(substratum=None))
    job = _staged(tmp_path, _request(tmp_path))

    outcome = run(job, exit_code_for=exit_code_for)

    assert (outcome.status, outcome.exit_code) == ("failed", EXIT_VALIDATION)
    assert "produced no substratum" in outcome.errors[0]["detail"]


def test_an_interrupted_job_is_written_dismissed_and_the_interrupt_goes_on(tmp_path, monkeypatch):
    monkeypatch.setattr(worker, "build_domain", Mock(side_effect=KeyboardInterrupt))
    job = _staged(tmp_path, _request(tmp_path))

    with pytest.raises(KeyboardInterrupt):
        run(job, exit_code_for=exit_code_for)

    assert read_document(job.outcome_path)["status"] == "dismissed"
    assert not job.is_sealed


@pytest.mark.parametrize("first", [{"mask_layer": None}, {"mask_layer": "watershed"}], ids=["default_spelled_out", "only_layer_named"])  # fmt: skip
def test_two_spellings_of_one_request_are_one_job(tmp_path, first):
    """The address is taken on the effective inputs. Both requests are written before either runs,
    since a GeoPackage rewritten later carries other bytes."""
    jobs = [_staged(tmp_path, _request(tmp_path, inputs=inputs), name=name) for name, inputs in (("one", first), ("two", {}))]  # fmt: skip
    one, two = (run(job, exit_code_for=exit_code_for) for job in jobs)

    assert one.status == "successful", one.errors
    assert two.job_id == one.job_id


def test_the_same_directory_submitted_twice_is_reported_and_not_run_again(tmp_path):
    job = _staged(tmp_path, _request(tmp_path))
    outcome = run(job, exit_code_for=exit_code_for)
    sealed_at = job.manifest_path.stat().st_mtime_ns

    again = run(job, exit_code_for=exit_code_for)

    assert (again.reused, again.job_id) == (True, outcome.job_id)
    assert job.manifest_path.stat().st_mtime_ns == sealed_at


@pytest.mark.parametrize(
    ("request_text", "match"),
    [
        (lambda t: json.dumps(_request(t, inputs={"depth_model": {"kind": "constant_thickness", "thickness": 12.5}})), "sealed"),
        (lambda t: "{}", "does not resolve into a job id"),
    ],
    ids=["another_job", "no_job_at_all"],
)  # fmt: skip
def test_a_sealed_directory_is_refused_rather_than_overwritten(tmp_path, request_text, match):
    job = _staged(tmp_path, _request(tmp_path))
    run(job, exit_code_for=exit_code_for)
    before = read_document(job.manifest_path)
    job.request_path.write_text(request_text(tmp_path), encoding="utf-8")

    with pytest.raises(JobUsageError, match=match):
        run(job, exit_code_for=exit_code_for)

    assert read_document(job.manifest_path) == before


RUN_JOB = """\
from hydromodpy.cli.exit_codes import exit_code_for
from hydromodpy.schema.job.directory import JobDirectory
from hydromodpy.model.domain.worker import run
"""


def _run_script(script: str, *args: object, **env: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-c", script, *map(str, args)], env=dict(os.environ, HMP_NO_PROGRESS="1", **env),
                          capture_output=True, text=True, timeout=600, check=False)  # fmt: skip


@pytest.mark.allow_subprocess
def test_it_writes_nowhere_but_the_job_directory_it_was_given(tmp_path):
    """``writes_outside_jobdir`` is empty. GDAL opens descriptors in C that no Python spy sees,
    so the controlled ``HOME`` and the empty scratch afterwards cover what survives."""
    created, scratch, home = tmp_path / "created.json", tmp_path / "scratch", tmp_path / "home"
    scratch.mkdir()
    home.mkdir()
    job = _staged(tmp_path, _request(tmp_path))
    script = WRITE_SPIES + "import json, os, sys\n" + RUN_JOB + (
        "outcome = run(JobDirectory.open(sys.argv[1]), exit_code_for=exit_code_for)\n"
        "real_bopen(sys.argv[2], 'w').write(json.dumps(seen))\n"
        "sys.exit(outcome.exit_code)\n"
    )  # fmt: skip

    completed = _run_script(script, job.root, created, TMPDIR=str(scratch), HOME=str(home))

    assert completed.returncode == 0, completed.stderr[-4000:]
    paths = [Path(entry).resolve() for entry in json.loads(created.read_text(encoding="utf-8"))]
    assert not DOMAIN_BUILD.writes_outside_jobdir, "this gate is written against an empty declaration; widen it first"  # fmt: skip
    # ``platform.platform()`` shells out through ``subprocess``, which opens ``os.devnull``.
    outside = [p for p in paths if p != Path(os.devnull) and not p.is_relative_to(job.root.resolve())]  # fmt: skip
    assert not outside, f"it writes into {outside}, which it does not declare"
    assert list(scratch.iterdir()) == [], "it left something under TMPDIR"
    assert list(home.iterdir()) == [], "it left something in the user's home directory"


LOCAL_NAMES = frozenset({"localhost", "localhost.localdomain", "ip6-localhost"})
# ``git`` from the provenance document, ``uname -p`` from ``platform.platform()``.
CHILD_PROCESSES_THE_JOB_SPAWNS = ("git", "uname")

NETWORK_SPIES = """\
import contextlib, json, socket, subprocess, sys
names, addrs, spawned = [], [], []
real_addrinfo, real_connect, real_popen = socket.getaddrinfo, socket.socket.connect, subprocess.Popen.__init__
def spy_addrinfo(host, port, *a, **k): names.append([host, port]); return real_addrinfo(host, port, *a, **k)
def spy_connect(self, address, *a, **k): addrs.append(list(address) if isinstance(address, tuple) else [address]); return real_connect(self, address, *a, **k)
def spy_popen(self, args, *a, **k): spawned.append(args if isinstance(args, str) else list(args)); return real_popen(self, args, *a, **k)
socket.getaddrinfo, socket.socket.connect, subprocess.Popen.__init__ = spy_addrinfo, spy_connect, spy_popen
socket.getaddrinfo('localhost', 9)
with contextlib.suppress(OSError), socket.socket() as probe:
    probe.connect(('127.0.0.1', 9))
subprocess.run([sys.executable, '-c', ''], capture_output=True)
sentinel = {'names': list(names), 'addrs': list(addrs), 'spawned': list(spawned)}
names.clear(), addrs.clear(), spawned.clear()
"""


def _is_local(value: object) -> bool:
    """True when *value* names this machine, in any of its spellings."""
    text = str(value).casefold().rstrip(".")
    if text in LOCAL_NAMES:
        return True
    for parse in (str, lambda digits: int(digits, 0)):
        with contextlib.suppress(ValueError, TypeError):
            return ipaddress.ip_address(parse(text)).is_loopback
    return False


@pytest.mark.allow_subprocess
def test_the_only_hosts_it_contacts_are_the_ones_it_declares(tmp_path):
    """``reaches_network`` is empty. A resolved host is caught by name, a hardcoded address by
    address, and a child process by its executable. The gate name is pinned in
    ``tests/unit/schema/test_capability_egress_gates.py``."""
    seen = tmp_path / "seen.json"
    job = _staged(tmp_path, _request(tmp_path))
    script = NETWORK_SPIES + RUN_JOB + (
        "try:\n"
        "    outcome = run(JobDirectory.open(sys.argv[1]), exit_code_for=exit_code_for)\n"
        "finally:\n"
        "    open(sys.argv[2], 'w').write(json.dumps({'sentinel': sentinel, 'names': names, 'addrs': addrs, 'spawned': spawned}))\n"
        "sys.exit(outcome.exit_code)\n"
    )  # fmt: skip

    completed = _run_script(script, job.root, seen)

    assert completed.returncode == 0, completed.stderr[-4000:]
    recorded = json.loads(seen.read_text(encoding="utf-8"))
    sentinel = recorded["sentinel"]
    assert sentinel["names"] and sentinel["addrs"] and sentinel["spawned"], "a spy caught nothing of the harness's own, so it is not installed"  # fmt: skip
    assert all(_is_local(entry[0]) for entry in sentinel["names"] + sentinel["addrs"]), "the locality filter does not recognise the local machine"  # fmt: skip
    declared = set(DOMAIN_BUILD.reaches_network)
    undeclared = sorted({str(e[0]) for e in recorded["names"] if not _is_local(e[0])} - declared)
    assert not undeclared, f"it resolves {undeclared}, which it does not declare"
    egress = sorted({str(e[0]) for e in recorded["addrs"] if not _is_local(e[0])} - declared)
    assert not egress, f"it connects to {egress}, which it does not declare"
    children = sorted({Path(argv[0] if isinstance(argv, list) else argv).name for argv in recorded["spawned"]})  # fmt: skip
    assert children == sorted(CHILD_PROCESSES_THE_JOB_SPAWNS), f"it spawns {children}, beyond what is accounted for"  # fmt: skip
