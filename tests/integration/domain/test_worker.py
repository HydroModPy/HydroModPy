"""``domain-build`` invoked the way an orchestrator invokes it.

One directory in, one seal out. These tests read the directory the way a
stranger would -- with ``rasterio``, ``geopandas`` and ``json``, never through
the objects that wrote it -- because what the boundary promises is that a third
party can do exactly that.

The terrain is synthetic and written here: 20 x 20 cells of 25 m in EPSG:2154
carrying a tilted plane, with a 2 x 2 block of nodata inside the mask so the
sentinel and the mask are exercised by the same run. Synthetic and not the
delineated valley of ``terrain-delineate`` on purpose: this capability builds a
geometry out of any raster, and binding its tests to the one engine that is not
fork-safe under xdist would be paying for a dependency it does not have.
"""

from __future__ import annotations

import ipaddress
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.cli.helpers import EXIT_CONFIG, EXIT_NOT_FOUND, EXIT_VALIDATION, exit_code_for
from hydromodpy.core.exceptions import JobUsageError
from hydromodpy.schema.job import JobDirectory, read_document, verify_job
from hydromodpy.schema.job.digest import sha256_file
from hydromodpy.schema.job.layout import ALLOWED_JOB_ENTRIES
from hydromodpy.spatial.domain import worker
from hydromodpy.spatial.domain.build import build_domain
from hydromodpy.spatial.domain.capability import (
    ACTIVE_CELLS_PATH,
    BOTTOM_PATH,
    DOMAIN_BUILD,
    DOMAIN_DOCUMENT_PATH,
    THICKNESS_PATH,
)
from hydromodpy.spatial.domain.domain_config import DomainConfig
from hydromodpy.spatial.domain.worker import run
from hydromodpy.spatial.geographic.core.surface_from_dem import build_surface_topo_from_dem
from tests._helpers.domain_cases import write_mask
from tests._helpers.geotiffs import write_geotiff
from tests._helpers.process_spies import WRITE_SPIES

gpd = pytest.importorskip("geopandas")
rasterio = pytest.importorskip("rasterio")

CRS = "EPSG:2154"
CELL = 25.0
SIZE = 20
XMIN = 300000.0
YMAX = 6700500.0
NODATA = -9999.0

NODATA_ROWS = slice(5, 7)
NODATA_COLS = slice(5, 7)
"""A 2 x 2 hole, placed inside the mask so both exclusions meet on one run."""

MASK_BOX = (300100.0, 6700100.0, 300400.0, 6700400.0)
ELSEWHERE = (400000.0, 6800000.0, 400100.0, 6800100.0)
CELLS_UNDER_MASK = 144
"""12 x 12 cell centres fall inside the box; counted from the grid, not guessed."""

ACTIVE_CELLS = CELLS_UNDER_MASK - 4
"""The four nodata cells sit under the mask and are not part of the domain."""

THICKNESS = 30.0
FLAT = {"kind": "flat_substratum", "substratum_elevation": 60.0}


def _elevation() -> np.ndarray:
    rows, cols = np.indices((SIZE, SIZE))
    return 100.0 + 0.5 * cols + 0.25 * rows


def _raster(path: Path, values: np.ndarray, *, crs: str | None = CRS) -> Path:
    """Write *values* on the grid of the terrain."""
    return write_geotiff(path, values, origin=(XMIN, YMAX), cell=CELL, crs=crs, nodata=NODATA)


def _dem(path: Path, *, crs: str | None = CRS) -> Path:
    """Write the synthetic terrain, with its hole punched."""
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
    document: dict[str, object] = {
        "process": {"id": "domain-build", "version": "1.0.0"},
        "inputs": inputs,
    }
    document.update(overrides)
    return document


def _staged(tmp_path: Path, document: dict, *, name: str = "job") -> JobDirectory:
    job = JobDirectory.create(tmp_path / name)
    job.request_path.write_text(json.dumps(document), encoding="utf-8")
    return job


def _band(job: JobDirectory, relative: str) -> np.ndarray:
    with rasterio.open(str(job.resolve_output(relative))) as source:
        return source.read(1)


def _succeeds(tmp_path: Path, **inputs: object) -> JobDirectory:
    job = _staged(tmp_path, _request(tmp_path, inputs=inputs))
    outcome = run(job, exit_code_for=exit_code_for)
    assert outcome.status == "successful", outcome.errors
    return job


@pytest.fixture
def sealed_job(tmp_path):
    job = _staged(tmp_path, _request(tmp_path))
    outcome = run(job, exit_code_for=exit_code_for)
    assert outcome.status == "successful", outcome.errors
    return job, outcome


def test_a_finished_job_is_sealed_with_the_declared_artefacts_and_nothing_else(sealed_job):
    job, outcome = sealed_job
    declared = {
        output.path.removeprefix("outputs/")
        for output in DOMAIN_BUILD.outputs
        if output.path.startswith("outputs/")
    }

    assert job.is_sealed
    assert verify_job(job).ok
    assert {entry.name for entry in job.root.iterdir()} <= ALLOWED_JOB_ENTRIES
    assert {entry.name for entry in job.outputs_dir.iterdir()} == declared
    assert read_document(job.manifest_path)["job_id"] == outcome.job_id
    assert read_document(job.outcome_path)["job_id"] == outcome.job_id
    assert outcome.job_id.startswith("sha256:")


def test_every_raster_lands_on_the_grid_of_the_terrain_and_is_nan_outside_the_domain(sealed_job):
    """No resampling, no reprojection, no clip: the mask says which cells are
    active, never which cells exist.

    The DEM's own sentinel is not a safe nodata for the two elevation rasters.
    ``Surface.flat_like`` clamps a nodata cell to ``top - min_gap`` rather than
    leaving it at ``-9999``, and neither depth model marks a cell the *mask*
    excluded: a consumer masking on the declared tag would read a fabricated
    elevation at both. NaN is what is written and what is declared.
    """
    job, _ = sealed_job
    inactive = ~_band(job, ACTIVE_CELLS_PATH).astype(bool)

    with rasterio.open(str(job.root.parent / "dem.tif")) as terrain:
        reference = (terrain.shape, terrain.transform, terrain.crs)
    for relative in (BOTTOM_PATH, THICKNESS_PATH, ACTIVE_CELLS_PATH):
        with rasterio.open(str(job.resolve_output(relative))) as produced:
            assert (produced.shape, produced.transform, produced.crs) == reference, relative
            if relative != ACTIVE_CELLS_PATH:
                assert np.isnan(produced.nodata), relative
                assert np.isnan(produced.read(1)[inactive]).all(), relative
    # Both exclusions are present in this run, so neither is asserted vacuously.
    assert inactive[NODATA_ROWS, NODATA_COLS].all()
    assert inactive[0, 0]


def test_the_bottom_and_thickness_are_the_runtime_geometry_on_the_active_cells(sealed_job):
    """One constructor, and a capability that proves it: a body that reimplemented
    the vertical extent would seal an artefact unrelated to what ``run_setup`` builds."""
    job, _ = sealed_job
    active = _band(job, ACTIVE_CELLS_PATH).astype(bool)
    runtime = build_domain(
        DomainConfig.with_thickness(THICKNESS),
        surface_topo=build_surface_topo_from_dem(job.root.parent / "dem.tif"),
    )

    np.testing.assert_allclose(_band(job, BOTTOM_PATH)[active], _elevation()[active] - THICKNESS)
    np.testing.assert_array_equal(
        _band(job, BOTTOM_PATH)[active], runtime.substratum.as_array()[active]
    )
    np.testing.assert_allclose(_band(job, THICKNESS_PATH)[active], THICKNESS)


def test_the_document_counts_the_active_cells_and_names_the_terrain_digest(sealed_job):
    """A mean over the whole grid would average the sentinel into an elevation.
    The top is not re-emitted, so a reader holding a DEM proves it by its digest."""
    job, _ = sealed_job
    document = read_document(job.resolve_output(DOMAIN_DOCUMENT_PATH))
    active = _band(job, ACTIVE_CELLS_PATH).astype(bool)

    assert int(active.sum()) == ACTIVE_CELLS
    assert document["active_cells"]["count"] == ACTIVE_CELLS
    assert document["active_cells"]["total"] == SIZE * SIZE
    assert document["active_cells"]["area_m2"] == pytest.approx(ACTIVE_CELLS * CELL * CELL)
    assert document["statistics"]["over"] == "active_cells"
    assert document["statistics"]["top"]["mean"] == pytest.approx(
        float(_elevation()[active].mean())
    )
    assert document["statistics"]["top"]["min"] > NODATA
    assert document["layers"][0]["top"] == {
        "input": "dem",
        "sha256": sha256_file(job.root.parent / "dem.tif")[0],
    }
    assert document["layers"][0]["bottom"] == BOTTOM_PATH
    assert document["crs"] == CRS


def test_a_flat_substratum_puts_the_bottom_at_its_elevation_and_none_at_a_nodata_cell(tmp_path):
    """``flat_like`` clamps ``-9999`` to ``-10000``, so the sentinel does not
    survive the depth model that uses it. Before the fix the raster declared
    ``-9999`` and held ``-10000`` at those cells."""
    job = _succeeds(tmp_path, depth_model=FLAT)

    bottom = _band(job, BOTTOM_PATH)
    np.testing.assert_allclose(bottom[_band(job, ACTIVE_CELLS_PATH).astype(bool)], 60.0)
    assert np.isnan(bottom[NODATA_ROWS, NODATA_COLS]).all()
    assert not (bottom == -10000.0).any()
    assert read_document(job.resolve_output(DOMAIN_DOCUMENT_PATH))["depth_model"] == FLAT
    # The clamp is still there one layer down, so this test cannot pass because
    # the mechanism it guards against went away.
    runtime = build_domain({"depth_model": FLAT}, surface_topo=build_surface_topo_from_dem(job.root.parent / "dem.tif"))  # fmt: skip
    assert (runtime.substratum.as_array()[NODATA_ROWS, NODATA_COLS] == -10000.0).all()


def test_without_a_mask_every_cell_carrying_data_is_active(tmp_path):
    job = _succeeds(tmp_path, mask=None)

    assert int(_band(job, ACTIVE_CELLS_PATH).sum()) == SIZE * SIZE - 4
    assert read_document(job.resolve_output(DOMAIN_DOCUMENT_PATH))["active_cells"]["mask"] is None


def test_a_terrain_without_nodata_pinned_by_its_own_digest_leaves_the_mask_alone_to_decide(
    tmp_path,
):
    plain = write_geotiff(tmp_path / "plain.tif", _elevation(), origin=(XMIN, YMAX), cell=CELL)

    job = _succeeds(tmp_path, dem={"href": str(plain), "sha256": sha256_file(plain)[0].upper()})

    assert int(_band(job, ACTIVE_CELLS_PATH).sum()) == CELLS_UNDER_MASK


def test_the_named_layer_is_the_one_read(tmp_path):
    both = write_mask(tmp_path / "two.gpkg", {"inside": MASK_BOX, "outside": ELSEWHERE})

    job = _succeeds(tmp_path, mask={"href": str(both)}, mask_layer="inside")

    assert int(_band(job, ACTIVE_CELLS_PATH).sum()) == ACTIVE_CELLS


def test_a_mask_in_another_crs_is_brought_onto_the_terrain(tmp_path):
    from shapely.geometry import box

    lonlat = tmp_path / "lonlat.gpkg"
    gpd.GeoDataFrame(geometry=[box(*MASK_BOX)], crs=CRS).to_crs("EPSG:4326").to_file(str(lonlat), layer="watershed")  # fmt: skip

    job = _succeeds(tmp_path, mask={"href": str(lonlat)})

    assert int(_band(job, ACTIVE_CELLS_PATH).sum()) == ACTIVE_CELLS


def test_a_terrain_of_several_bands_is_read_on_band_one_and_says_so(tmp_path):
    """Accepted, because a DEM shipped as band 1 of a stack is legitimate, and
    warned about, because the other bands are silently ignored."""
    stack = np.stack([_elevation(), np.zeros((SIZE, SIZE)), np.zeros((SIZE, SIZE))])
    stacked = write_geotiff(tmp_path / "stacked.tif", stack, origin=(XMIN, YMAX), cell=CELL, nodata=NODATA)  # fmt: skip
    job = _staged(tmp_path, _request(tmp_path, inputs={"dem": {"href": str(stacked)}}))

    outcome = run(job, exit_code_for=exit_code_for)

    assert outcome.status == "successful", outcome.errors
    assert any("band 1 is read" in warning for warning in outcome.warnings)
    active = _band(job, ACTIVE_CELLS_PATH).astype(bool)
    np.testing.assert_allclose(_band(job, BOTTOM_PATH)[active], _elevation()[active] - THICKNESS)


def _rotated(tmp_path: Path) -> dict:
    """A sheared grid has no ``dx`` and no ``dy``: the document would publish two
    numbers that are not the cell size."""
    from affine import Affine

    path = tmp_path / "rotated.tif"
    with rasterio.open(
        str(path), "w", driver="GTiff", height=SIZE, width=SIZE, count=1, dtype="float64", crs=CRS,
        transform=Affine(CELL, 5.0, XMIN, 5.0, -CELL, YMAX), nodata=NODATA,
    ) as sink:  # fmt: skip
        sink.write(_elevation(), 1)
    return {"dem": {"href": str(path)}, "mask": None}


def _lines(tmp_path: Path) -> dict:
    """A hydrographic network handed in where a catchment was meant: rasterized,
    a line burns a one-cell-wide diagonal and the job succeeds with a sliver."""
    from shapely.geometry import LineString

    path = tmp_path / "network.gpkg"
    line = LineString([(300100.0, 6700100.0), (300400.0, 6700400.0)])
    gpd.GeoDataFrame({"name": ["talweg"]}, geometry=[line], crs=CRS).to_file(
        str(path), layer="network"
    )
    return {"mask": {"href": str(path)}}


def _empty_layer(tmp_path: Path) -> dict:
    path = tmp_path / "empty.gpkg"
    gpd.GeoDataFrame({"name": ["nothing"]}, geometry=[None], crs=CRS).to_file(
        str(path), layer="watershed"
    )
    return {"mask": {"href": str(path)}}


def _text(tmp_path: Path, name: str) -> str:
    path = tmp_path / name
    path.write_text("not a dataset", encoding="utf-8")
    return str(path)


def _substratum(
    tmp_path: Path, values: np.ndarray | None, *, crs: str | None = CRS, **depth_model
) -> dict:
    inputs: dict[str, object] = {"depth_model": {"kind": "raster_substratum", **depth_model}}
    if values is not None:
        inputs["substratum"] = {"href": str(_raster(tmp_path / "substratum.tif", values, crs=crs))}
    return inputs


def _left_half() -> np.ndarray:
    values = np.full((SIZE, SIZE), NODATA)
    values[:, :10] = 60.0
    return values


POINTER = '"pointer": "/inputs/{}"'


@pytest.mark.parametrize(
    ("inputs", "request_overrides", "exit_code", "fragments", "untouched"),
    [
        (lambda t: {"dem": {"href": str(_dem(t / "bare.tif", crs=None))}}, {}, EXIT_VALIDATION, ("carries no CRS",), True),
        (lambda t: {"dem": {"href": _text(t, "text.tif")}}, {}, EXIT_VALIDATION, ("cannot be opened as a raster",), True),
        (lambda t: {"dem": {"href": str(t / "dem.tif"), "sha256": "00" * 32}}, {}, EXIT_VALIDATION, ("the bytes are not the ones the job asked for",), True),
        (lambda t: {"dem": {"href": str(t / "absent.tif")}}, {}, EXIT_NOT_FOUND, (), True),
        (_rotated, {}, EXIT_VALIDATION, ("rotated or sheared transform",), True),
        (lambda t: {"mask": {"href": str(write_mask(t / "far.gpkg", {"watershed": ELSEWHERE}))}}, {}, EXIT_VALIDATION, ("no cell of the terrain is active",), False),
        (lambda t: {"mask": {"href": str(write_mask(t / "two.gpkg", {"first": MASK_BOX, "second": MASK_BOX}))}}, {}, EXIT_CONFIG, (POINTER.format("mask_layer"),), True),
        (lambda t: {"mask": None, "mask_layer": "watershed"}, {}, EXIT_CONFIG, (POINTER.format("mask_layer"),), True),
        (lambda t: {"mask_layer": "catchment"}, {}, EXIT_CONFIG, ("holds no layer named 'catchment'", POINTER.format("mask_layer")), True),
        (lambda t: {"mask": {"href": _text(t, "text.gpkg")}}, {}, EXIT_VALIDATION, ("cannot be opened as a vector dataset",), True),
        (lambda t: {"mask": {"href": str(write_mask(t / "bare.gpkg", {"watershed": MASK_BOX}, crs=None))}}, {}, EXIT_VALIDATION, ("carries no CRS, so it cannot be placed",), False),
        (_empty_layer, {}, EXIT_VALIDATION, ("holds no geometry to bound the domain",), False),
        (_lines, {}, EXIT_VALIDATION, ("holds LineString geometries",), False),
        (lambda t: {"depth_model": {"kind": "flat_substratum", "substratum_elevation": 5000.0}}, {}, EXIT_CONFIG, ('"code": "HMPY.E101"', POINTER.format("depth_model")), False),
        (lambda t: {}, {"outputs": {"mesh": {}}}, EXIT_CONFIG, (), True),
        (lambda t: _substratum(t, _left_half()), {}, EXIT_VALIDATION, ("without a value",), False),
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
    """A bad input is the caller's fault: a typed exit code, never ``HMPY.E000`` and exit 1,
    the code whose whole meaning is "this is a bug in HydroModPy, report it"."""
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
    monkeypatch.setattr(
        worker, "build_domain", lambda *args, **kwargs: SimpleNamespace(substratum=None)
    )
    job = _staged(tmp_path, _request(tmp_path))

    outcome = run(job, exit_code_for=exit_code_for)

    assert (outcome.status, outcome.exit_code) == ("failed", EXIT_VALIDATION)
    assert "produced no substratum" in outcome.errors[0]["detail"]


def test_an_interrupted_job_is_written_dismissed_and_the_interrupt_goes_on(tmp_path, monkeypatch):
    def interrupt(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(worker, "build_domain", interrupt)
    job = _staged(tmp_path, _request(tmp_path))

    with pytest.raises(KeyboardInterrupt):
        run(job, exit_code_for=exit_code_for)

    assert read_document(job.outcome_path)["status"] == "dismissed"
    assert not job.is_sealed


@pytest.mark.parametrize(
    ("first", "second"),
    [({"mask_layer": None}, {}), ({"mask_layer": "watershed"}, {})],
    ids=["default_spelled_out", "only_layer_named"],
)
def test_two_spellings_of_one_request_are_one_job(tmp_path, first, second):
    """The address is taken on the effective inputs, defaults applied and the mask
    layer resolved, so an orchestrator does not queue the same work twice."""
    # Both requests are written before either runs: a GeoPackage rewritten later
    # carries other bytes, and so another job id.
    jobs = [_staged(tmp_path, _request(tmp_path, inputs=inputs), name=name) for name, inputs in (("one", first), ("two", second))]  # fmt: skip
    one, two = (run(job, exit_code_for=exit_code_for) for job in jobs)

    assert one.status == "successful", one.errors
    assert two.job_id == one.job_id


def test_the_same_directory_submitted_twice_is_reported_and_not_run_again(tmp_path):
    job = _staged(tmp_path, _request(tmp_path))
    outcome = run(job, exit_code_for=exit_code_for)
    sealed_at = job.manifest_path.stat().st_mtime_ns

    again = run(job, exit_code_for=exit_code_for)

    assert again.reused is True
    assert again.job_id == outcome.job_id
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


@pytest.mark.allow_subprocess
def test_it_writes_nowhere_but_the_job_directory_it_was_given(tmp_path):
    """``writes_outside_jobdir`` is empty, and this is what holds it to be true.

    The ceiling is the one the ``data-request`` gate states: GDAL opens its own
    descriptors in C and no Python-level spy sees them. The controlled ``HOME``
    and the emptiness of the scratch afterwards cover the part that survives.
    """
    created = tmp_path / "created.json"
    scratch = tmp_path / "scratch"
    home = tmp_path / "home"
    scratch.mkdir()
    home.mkdir()
    job = _staged(tmp_path, _request(tmp_path))

    script = (
        WRITE_SPIES + "import json, os, sys\n"
        "from hydromodpy.cli.helpers import exit_code_for\n"
        "from hydromodpy.schema.job import JobDirectory\n"
        "from hydromodpy.spatial.domain.worker import run\n"
        "outcome = run(JobDirectory.open(sys.argv[1]), exit_code_for=exit_code_for)\n"
        "real_bopen(sys.argv[2], 'w').write(json.dumps(seen))\n"
        "sys.exit(outcome.exit_code)\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", script, str(job.root), str(created)],
        env=dict(os.environ, TMPDIR=str(scratch), HOME=str(home), HMP_NO_PROGRESS="1"),
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr[-4000:]
    paths = [Path(entry).resolve() for entry in json.loads(created.read_text(encoding="utf-8"))]
    assert not DOMAIN_BUILD.writes_outside_jobdir, (
        "this gate is written against an empty declaration; widen it first"
    )
    # The null device is not the filesystem, and it is reached for the measured
    # reason the terrain gate names: ``platform.platform()`` shells out through
    # ``subprocess``, which opens ``os.devnull`` for the child's stderr.
    paths = [path for path in paths if path != Path(os.devnull)]
    outside = [path for path in paths if not path.is_relative_to(job.root.resolve())]

    assert not outside, f"it writes into {outside}, which it does not declare"
    assert list(scratch.iterdir()) == [], "it left something under TMPDIR"
    assert list(home.iterdir()) == [], "it left something in the user's home directory"


LOCAL_NAMES = frozenset({"localhost", "localhost.localdomain", "ip6-localhost"})
"""Names of the local machine. Not egress: reachable with no route out at all."""

CHILD_PROCESSES_THE_JOB_SPAWNS = ("git", "uname")
"""The two the whole family spawns: ``git`` from the provenance document, and
``uname -p`` from ``platform.platform()`` unpacking a ``uname_result``."""


def _is_local(value: object) -> bool:
    """True when *value* names this machine, in any of its spellings."""
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
    """``reaches_network`` is empty, and a claim of that shape needs a spy.

    Three angles, because two are not enough: a host resolved through
    ``getaddrinfo`` is caught by name, a connection opened straight to a
    hardcoded address resolves nothing and is caught by address, and a child
    process does its networking in an interpreter this one cannot patch, so it
    is caught by the name of the executable instead.

    That every served capability has a gate of this name is pinned in
    ``tests/unit/schema/test_capability_egress_gates.py``.
    """
    seen = tmp_path / "seen.json"
    job = _staged(tmp_path, _request(tmp_path))

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
        "from hydromodpy.spatial.domain.worker import run\n"
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
    completed = subprocess.run(
        [sys.executable, "-c", script, str(job.root), str(seen)],
        env=dict(os.environ, HMP_NO_PROGRESS="1"),
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
    assert all(_is_local(entry[0]) for entry in sentinel["names"] + sentinel["addrs"]), (
        "the locality filter does not recognise the local machine it was handed"
    )

    declared = set(DOMAIN_BUILD.reaches_network)
    undeclared = sorted(
        {str(entry[0]) for entry in recorded["names"] if not _is_local(entry[0])} - declared
    )
    assert not undeclared, f"it resolves {undeclared}, which it does not declare"
    egress = sorted(
        {str(entry[0]) for entry in recorded["addrs"] if not _is_local(entry[0])} - declared
    )
    assert not egress, f"it connects to {egress}, which it does not declare"
    children = sorted(
        {Path(argv[0] if isinstance(argv, list) else argv).name for argv in recorded["spawned"]}
    )
    assert children == sorted(CHILD_PROCESSES_THE_JOB_SPAWNS), (
        f"it spawns {children}, and only {sorted(CHILD_PROCESSES_THE_JOB_SPAWNS)} is accounted for"
    )


def test_a_raster_substratum_places_the_bottom_and_the_seal_names_its_digest(tmp_path):
    bottom = _elevation() - 40.0
    job = _staged(tmp_path, _request(tmp_path, inputs=_substratum(tmp_path, bottom)))

    outcome = run(job, exit_code_for=exit_code_for)

    assert outcome.status == "successful", outcome.errors
    assert verify_job(job).ok
    active = _band(job, ACTIVE_CELLS_PATH).astype(bool)
    np.testing.assert_allclose(_band(job, BOTTOM_PATH)[active], bottom[active])
    digest, _size = sha256_file(tmp_path / "substratum.tif")
    layer = read_document(job.resolve_output(DOMAIN_DOCUMENT_PATH))["layers"][0]
    assert layer["substratum"] == {"input": "substratum", "sha256": digest}
    resources = read_document(job.inputset_path)["resources"]
    assert {"name": "substratum", "sha256": digest} in [
        {"name": r["name"], "sha256": r["sha256"]} for r in resources
    ]


def test_a_raster_covering_the_mask_alone_serves_a_masked_terrain(tmp_path):
    """The mask is the extent: cells outside it need no substratum value."""
    values = np.full((SIZE, SIZE), NODATA)
    values[3:17, 3:17] = 60.0

    job = _succeeds(tmp_path, **_substratum(tmp_path, values))

    np.testing.assert_allclose(
        _band(job, BOTTOM_PATH)[_band(job, ACTIVE_CELLS_PATH).astype(bool)], 60.0
    )


def test_a_request_without_a_substratum_keeps_the_job_id_it_had_before_the_member(sealed_job):
    """Adding the member must not re-address the jobs already sealed."""
    from hydromodpy.schema.job.request import content_address
    from hydromodpy.spatial.domain.capability import DomainBuildRequest

    job, outcome = sealed_job
    inputs = read_document(job.request_path)["inputs"]
    payload = DomainBuildRequest.model_validate(inputs).model_dump(mode="json")
    payload.pop("substratum")
    payload["dem"] = {"sha256": sha256_file(Path(inputs["dem"]["href"]))[0]}
    payload["mask"] = {"sha256": sha256_file(Path(inputs["mask"]["href"]))[0]}
    payload["mask_layer"] = "watershed"

    expected = content_address(
        process_id=DOMAIN_BUILD.id, process_version=DOMAIN_BUILD.version, inputs=payload
    )
    assert outcome.job_id == expected
