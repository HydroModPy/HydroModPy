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

import numpy as np
import pytest

from hydromodpy.cli.helpers import (
    EXIT_CONFIG,
    EXIT_NOT_FOUND,
    EXIT_VALIDATION,
    exit_code_for,
)
from hydromodpy.core.exceptions import JobUsageError
from hydromodpy.schema.job import JobDirectory, read_document, verify_job
from hydromodpy.schema.job.digest import sha256_file
from hydromodpy.schema.job.layout import ALLOWED_JOB_ENTRIES
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
CELLS_UNDER_MASK = 144
"""12 x 12 cell centres fall inside the box; counted from the grid, not guessed."""

ACTIVE_CELLS = CELLS_UNDER_MASK - 4
"""The four nodata cells sit under the mask and are not part of the domain."""

THICKNESS = 30.0


def _elevation() -> np.ndarray:
    rows, cols = np.indices((SIZE, SIZE))
    return 100.0 + 0.5 * cols + 0.25 * rows


def _dem(path: Path, *, nodata: float | None = NODATA, crs: str | None = CRS) -> Path:
    """Write the synthetic terrain, with its hole punched when it has one."""
    values = _elevation()
    if nodata is not None:
        values[NODATA_ROWS, NODATA_COLS] = nodata
    profile = {
        "driver": "GTiff",
        "height": SIZE,
        "width": SIZE,
        "count": 1,
        "dtype": "float64",
        "crs": crs,
        "transform": rasterio.transform.from_origin(XMIN, YMAX, CELL, CELL),
        "nodata": nodata,
    }
    with rasterio.open(str(path), "w", **profile) as sink:
        sink.write(values, 1)
    return path


def _mask(path: Path, *, layers: dict[str, tuple[float, ...]] | None = None) -> Path:
    """Write one GeoPackage holding one polygon per declared layer."""
    from shapely.geometry import box as shapely_box

    declared = layers if layers is not None else {"watershed": MASK_BOX}
    for index, (layer, box) in enumerate(declared.items()):
        gpd.GeoDataFrame({"site_id": [layer]}, geometry=[shapely_box(*box)], crs=CRS).to_file(
            str(path), driver="GPKG", layer=layer, mode="w" if index == 0 else "a"
        )
    return path


def _request(tmp_path: Path, **overrides: object) -> dict:
    inputs: dict[str, object] = {
        "dem": {"href": str(_dem(tmp_path / "dem.tif")), "type": "image/tiff; application=geotiff"},
        "depth_model": {"kind": "constant_thickness", "thickness": THICKNESS},
        "mask": {"href": str(_mask(tmp_path / "mask.gpkg"))},
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


@pytest.fixture
def sealed_job(tmp_path):
    job = _staged(tmp_path, _request(tmp_path))
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
        for output in DOMAIN_BUILD.outputs
        if output.path.startswith("outputs/")
    }

    assert {entry.name for entry in job.outputs_dir.iterdir()} == declared


def test_the_seal_and_the_outcome_name_one_job(sealed_job):
    job, outcome = sealed_job
    manifest = read_document(job.manifest_path)

    assert manifest["job_id"] == outcome.job_id
    assert read_document(job.outcome_path)["job_id"] == outcome.job_id
    assert outcome.job_id.startswith("sha256:")


def test_every_raster_lands_on_the_grid_of_the_terrain_it_was_given(sealed_job):
    """No resampling, no reprojection, no clip: the mask says which cells are
    active, never which cells exist."""
    job, _ = sealed_job

    with rasterio.open(str(job.root.parent / "dem.tif")) as terrain:
        reference = (terrain.shape, terrain.transform, terrain.crs)
    for relative in (BOTTOM_PATH, THICKNESS_PATH, ACTIVE_CELLS_PATH):
        with rasterio.open(str(job.resolve_output(relative))) as produced:
            assert (produced.shape, produced.transform, produced.crs) == reference, relative


def test_the_bottom_is_the_top_shifted_down_by_the_declared_thickness(sealed_job):
    job, _ = sealed_job
    top = _elevation()
    active = _band(job, ACTIVE_CELLS_PATH).astype(bool)

    np.testing.assert_allclose(_band(job, BOTTOM_PATH)[active], top[active] - THICKNESS)


def test_no_cell_outside_the_domain_carries_an_elevation_in_either_raster(sealed_job):
    """What the adversarial gate of F7e landed on, pinned from both sides.

    The DEM's own sentinel is not a safe nodata for these two rasters.
    ``Surface.flat_like`` clamps a nodata cell to ``top - min_gap`` rather than
    leaving it at ``-9999``, and neither depth model marks a cell the *mask*
    excluded: a consumer masking on the declared tag would read a fabricated
    elevation at both. NaN is what is written and what is declared.
    """
    job, _ = sealed_job
    inactive = ~_band(job, ACTIVE_CELLS_PATH).astype(bool)

    for relative in (BOTTOM_PATH, THICKNESS_PATH):
        assert np.isnan(_band(job, relative)[inactive]).all(), relative
        with rasterio.open(str(job.resolve_output(relative))) as produced:
            assert np.isnan(produced.nodata), relative
    # Both exclusions are present in this run, so neither is asserted vacuously.
    assert inactive[NODATA_ROWS, NODATA_COLS].all()
    assert inactive[0, 0]


def test_a_flat_substratum_leaves_no_elevation_at_a_nodata_cell_either(tmp_path):
    """The reproduction the adversarial gate wrote, turned into a test.

    ``flat_like`` clamps ``-9999`` to ``-10000``, so the sentinel does not
    survive the depth model that uses it. Before the fix the raster declared
    ``-9999`` and held ``-10000`` at those cells.
    """
    job = _staged(
        tmp_path,
        _request(
            tmp_path,
            inputs={"depth_model": {"kind": "flat_substratum", "substratum_elevation": 60.0}},
        ),
    )

    outcome = run(job, exit_code_for=exit_code_for)

    assert outcome.status == "successful", outcome.errors
    bottom = _band(job, BOTTOM_PATH)
    assert np.isnan(bottom[NODATA_ROWS, NODATA_COLS]).all()
    assert not (bottom == -10000.0).any()
    # And the clamp is still there, one layer down, so this test cannot pass
    # because the mechanism it guards against went away.
    runtime = build_domain(
        {"depth_model": {"kind": "flat_substratum", "substratum_elevation": 60.0}},
        surface_topo=build_surface_topo_from_dem(job.root.parent / "dem.tif"),
    )
    assert runtime.substratum is not None
    assert (runtime.substratum.as_array()[NODATA_ROWS, NODATA_COLS] == -10000.0).all()


def test_the_mask_decides_which_cells_are_active_and_the_document_counts_them(sealed_job):
    job, _ = sealed_job
    document = read_document(job.resolve_output(DOMAIN_DOCUMENT_PATH))

    assert int(_band(job, ACTIVE_CELLS_PATH).sum()) == ACTIVE_CELLS
    assert document["active_cells"]["count"] == ACTIVE_CELLS
    assert document["active_cells"]["total"] == SIZE * SIZE
    assert document["active_cells"]["area_m2"] == pytest.approx(ACTIVE_CELLS * CELL * CELL)


def test_the_thickness_is_the_vertical_extent_on_active_cells_and_nan_elsewhere(sealed_job):
    job, _ = sealed_job
    thickness = _band(job, THICKNESS_PATH)
    active = _band(job, ACTIVE_CELLS_PATH).astype(bool)

    np.testing.assert_allclose(thickness[active], THICKNESS)
    assert np.isnan(thickness[~active]).all()


def test_the_document_reports_the_extent_over_the_active_cells_only(sealed_job):
    """A mean over the whole grid would average the sentinel into an elevation,
    which is the defect that makes this document worth writing."""
    job, _ = sealed_job
    document = read_document(job.resolve_output(DOMAIN_DOCUMENT_PATH))
    top = _elevation()
    active = _band(job, ACTIVE_CELLS_PATH).astype(bool)

    assert document["statistics"]["over"] == "active_cells"
    assert document["statistics"]["top"]["mean"] == pytest.approx(float(top[active].mean()))
    assert document["statistics"]["top"]["min"] > NODATA


def test_the_document_names_the_digest_of_the_terrain_the_bottom_came_from(sealed_job):
    """The top is not re-emitted, so what makes the seal mean anything is that
    a reader holding a DEM can prove it is the one that was used."""
    job, _ = sealed_job
    document = read_document(job.resolve_output(DOMAIN_DOCUMENT_PATH))
    digest, _size = sha256_file(job.root.parent / "dem.tif")

    assert document["layers"][0]["top"] == {"input": "dem", "sha256": digest}
    assert document["layers"][0]["bottom"] == BOTTOM_PATH
    assert document["crs"] == CRS


def test_the_geometry_is_the_one_the_runtime_builds_from_the_same_section(sealed_job):
    """The point of the phase: one constructor, and a capability that proves it.

    A body that reimplemented the vertical extent would seal an artefact
    provably unrelated to what ``run_setup`` builds for a run.
    """
    job, _ = sealed_job
    runtime = build_domain(
        DomainConfig.with_thickness(THICKNESS),
        surface_topo=build_surface_topo_from_dem(job.root.parent / "dem.tif"),
    )

    active = _band(job, ACTIVE_CELLS_PATH).astype(bool)
    np.testing.assert_array_equal(
        _band(job, BOTTOM_PATH)[active], runtime.substratum.as_array()[active]
    )


def test_a_flat_substratum_puts_the_bottom_at_the_declared_elevation(tmp_path):
    job = _staged(
        tmp_path,
        _request(
            tmp_path,
            inputs={"depth_model": {"kind": "flat_substratum", "substratum_elevation": 60.0}},
        ),
    )

    outcome = run(job, exit_code_for=exit_code_for)

    assert outcome.status == "successful", outcome.errors
    active = _band(job, ACTIVE_CELLS_PATH).astype(bool)
    np.testing.assert_allclose(_band(job, BOTTOM_PATH)[active], 60.0)
    document = read_document(job.resolve_output(DOMAIN_DOCUMENT_PATH))
    assert document["depth_model"] == {"kind": "flat_substratum", "substratum_elevation": 60.0}


def test_without_a_mask_every_cell_carrying_data_is_active(tmp_path):
    job = _staged(tmp_path, _request(tmp_path, inputs={"mask": None}))

    outcome = run(job, exit_code_for=exit_code_for)

    assert outcome.status == "successful", outcome.errors
    assert int(_band(job, ACTIVE_CELLS_PATH).sum()) == SIZE * SIZE - 4
    assert read_document(job.resolve_output(DOMAIN_DOCUMENT_PATH))["active_cells"]["mask"] is None


def test_a_terrain_carrying_no_crs_is_refused_before_anything_is_built(tmp_path):
    """The working CRS is the terrain's own, so a terrain without one has none."""
    job = _staged(
        tmp_path,
        _request(
            tmp_path,
            inputs={"dem": {"href": str(_dem(tmp_path / "bare.tif", crs=None))}},
        ),
    )

    outcome = run(job, exit_code_for=exit_code_for)

    assert outcome.status == "failed"
    assert outcome.exit_code == EXIT_VALIDATION
    assert "carries no CRS" in outcome.errors[0]["detail"]
    assert not job.is_sealed


def test_a_mask_that_selects_no_cell_of_the_terrain_is_refused(tmp_path):
    job = _staged(
        tmp_path,
        _request(
            tmp_path,
            inputs={
                "mask": {
                    "href": str(
                        _mask(
                            tmp_path / "elsewhere.gpkg",
                            layers={"watershed": (400000.0, 6800000.0, 400100.0, 6800100.0)},
                        )
                    )
                }
            },
        ),
    )

    outcome = run(job, exit_code_for=exit_code_for)

    assert outcome.status == "failed"
    assert outcome.exit_code == EXIT_VALIDATION
    assert "no cell of the terrain is active" in outcome.errors[0]["detail"]


def test_a_mask_holding_several_layers_and_naming_none_is_refused_at_the_member(tmp_path):
    job = _staged(
        tmp_path,
        _request(
            tmp_path,
            inputs={
                "mask": {
                    "href": str(
                        _mask(
                            tmp_path / "two.gpkg",
                            layers={"first": MASK_BOX, "second": MASK_BOX},
                        )
                    )
                }
            },
        ),
    )

    outcome = run(job, exit_code_for=exit_code_for)

    assert outcome.status == "failed"
    assert outcome.exit_code == EXIT_CONFIG
    assert outcome.errors[0]["details"][0]["pointer"] == "/inputs/mask_layer"


def test_the_named_layer_is_the_one_read(tmp_path):
    both = _mask(
        tmp_path / "two.gpkg",
        layers={"inside": MASK_BOX, "outside": (400000.0, 6800000.0, 400100.0, 6800100.0)},
    )
    job = _staged(
        tmp_path,
        _request(
            tmp_path,
            inputs={"mask": {"href": str(both)}, "mask_layer": "inside"},
        ),
    )

    outcome = run(job, exit_code_for=exit_code_for)

    assert outcome.status == "successful", outcome.errors
    assert int(_band(job, ACTIVE_CELLS_PATH).sum()) == ACTIVE_CELLS


def test_a_layer_named_without_a_mask_to_read_it_from_is_refused(tmp_path):
    job = _staged(tmp_path, _request(tmp_path, inputs={"mask": None, "mask_layer": "watershed"}))

    outcome = run(job, exit_code_for=exit_code_for)

    assert outcome.status == "failed"
    assert outcome.exit_code == EXIT_CONFIG
    assert outcome.errors[0]["details"][0]["pointer"] == "/inputs/mask_layer"


def test_a_terrain_whose_bytes_are_not_the_ones_pinned_is_refused(tmp_path):
    job = _staged(
        tmp_path,
        _request(
            tmp_path,
            inputs={"dem": {"href": str(tmp_path / "dem.tif"), "sha256": "00" * 32}},
        ),
    )

    outcome = run(job, exit_code_for=exit_code_for)

    assert outcome.status == "failed"
    assert outcome.exit_code == EXIT_VALIDATION
    assert "the bytes are not the ones the job asked for" in outcome.errors[0]["detail"]


def test_a_terrain_that_is_not_on_disk_is_refused_as_a_missing_file(tmp_path):
    job = _staged(
        tmp_path, _request(tmp_path, inputs={"dem": {"href": str(tmp_path / "absent.tif")}})
    )

    outcome = run(job, exit_code_for=exit_code_for)

    assert outcome.status == "failed"
    assert outcome.exit_code == EXIT_NOT_FOUND


def test_an_output_nobody_declares_is_refused_before_the_run(tmp_path):
    job = _staged(tmp_path, _request(tmp_path, outputs={"mesh": {}}))

    outcome = run(job, exit_code_for=exit_code_for)

    assert outcome.status == "failed"
    assert outcome.exit_code == EXIT_CONFIG
    assert not job.is_sealed


def test_a_request_and_the_same_one_with_a_default_spelled_out_are_one_job(tmp_path):
    """The address is taken on the effective inputs, defaults applied, so a
    caller that spells a default and one that omits it do not queue twice."""
    spelled = _request(tmp_path)
    spelled["inputs"]["mask_layer"] = None
    omitted = _request(tmp_path)
    omitted["inputs"].pop("mask_layer", None)

    first = run(_staged(tmp_path, spelled, name="spelled"), exit_code_for=exit_code_for)
    second = run(_staged(tmp_path, omitted, name="omitted"), exit_code_for=exit_code_for)

    assert first.status == "successful", first.errors
    assert second.job_id == first.job_id


def test_the_same_directory_submitted_twice_is_reported_and_not_run_again(tmp_path):
    job = _staged(tmp_path, _request(tmp_path))
    outcome = run(job, exit_code_for=exit_code_for)
    sealed_at = job.manifest_path.stat().st_mtime_ns

    again = run(job, exit_code_for=exit_code_for)

    assert again.reused is True
    assert again.job_id == outcome.job_id
    assert job.manifest_path.stat().st_mtime_ns == sealed_at


def test_a_directory_sealed_under_another_job_is_refused_rather_than_overwritten(tmp_path):
    job = _staged(tmp_path, _request(tmp_path))
    run(job, exit_code_for=exit_code_for)
    before = read_document(job.manifest_path)
    job.request_path.write_text(
        json.dumps(
            _request(
                tmp_path,
                inputs={"depth_model": {"kind": "constant_thickness", "thickness": 12.5}},
            )
        ),
        encoding="utf-8",
    )

    with pytest.raises(JobUsageError):
        run(job, exit_code_for=exit_code_for)

    assert read_document(job.manifest_path) == before


@pytest.mark.allow_subprocess
def test_it_writes_nowhere_but_the_job_directory_it_was_given(tmp_path):
    """``writes_outside_jobdir`` is empty, and this is what holds it to be true.

    The ceiling is the one the ``data-fetch`` gate states: GDAL opens its own
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


def test_a_substratum_above_the_whole_terrain_is_refused_at_the_member(tmp_path):
    """A number the caller wrote, not a bug here.

    ``Surface.flat_like`` raises a bare ``ValueError`` when no aquifer would be
    left, and an uncaught one surfaces as ``HMPY.E000`` and exit 1 -- the code
    whose whole meaning is "this is a bug in HydroModPy, report it".
    """
    job = _staged(
        tmp_path,
        _request(
            tmp_path,
            inputs={"depth_model": {"kind": "flat_substratum", "substratum_elevation": 5000.0}},
        ),
    )

    outcome = run(job, exit_code_for=exit_code_for)

    assert outcome.status == "failed"
    assert outcome.exit_code == EXIT_CONFIG
    assert outcome.errors[0]["code"] == "HMPY.E101"
    assert outcome.errors[0]["details"][0]["pointer"] == "/inputs/depth_model"
    assert not job.is_sealed


def test_naming_the_only_layer_of_a_mask_addresses_the_same_job_as_not_naming_it(tmp_path):
    """The address is taken on the layer that was **resolved**.

    A file holding one layer is read the same way whether the request named it
    or left the choice to the file, so the two submissions are one job and an
    orchestrator does not queue the work twice.
    """
    named = _request(tmp_path)
    named["inputs"]["mask_layer"] = "watershed"
    silent = _request(tmp_path)

    first = run(_staged(tmp_path, named, name="named"), exit_code_for=exit_code_for)
    second = run(_staged(tmp_path, silent, name="silent"), exit_code_for=exit_code_for)

    assert first.status == "successful", first.errors
    assert second.job_id == first.job_id


def test_a_layer_the_mask_does_not_hold_is_refused_with_the_directory_untouched(tmp_path):
    job = _staged(tmp_path, _request(tmp_path, inputs={"mask_layer": "catchment"}))

    outcome = run(job, exit_code_for=exit_code_for)

    assert outcome.status == "failed"
    assert outcome.exit_code == EXIT_CONFIG
    assert "holds no layer named 'catchment'" in outcome.errors[0]["detail"]
    assert outcome.errors[0]["details"][0]["pointer"] == "/inputs/mask_layer"
    assert not job.outputs_dir.exists()


def test_a_mask_of_lines_is_refused_instead_of_burned_into_a_sliver(tmp_path):
    """The mistake the adversarial gate named: a hydrographic network handed in
    where a catchment was meant. Rasterized, a line burns a one-cell-wide
    diagonal and the job succeeds with a domain that is a sliver."""
    from shapely.geometry import LineString

    lines = tmp_path / "network.gpkg"
    gpd.GeoDataFrame(
        {"name": ["talweg"]},
        geometry=[LineString([(300100.0, 6700100.0), (300400.0, 6700400.0)])],
        crs=CRS,
    ).to_file(str(lines), driver="GPKG", layer="network")
    job = _staged(tmp_path, _request(tmp_path, inputs={"mask": {"href": str(lines)}}))

    outcome = run(job, exit_code_for=exit_code_for)

    assert outcome.status == "failed"
    assert outcome.exit_code == EXIT_VALIDATION
    assert "holds LineString geometries" in outcome.errors[0]["detail"]


def test_a_rotated_terrain_is_refused_rather_than_described_with_a_cell_size(tmp_path):
    """A sheared grid has no ``dx`` and no ``dy``, and the document would publish
    two numbers that are not the cell size."""
    from affine import Affine

    rotated = tmp_path / "rotated.tif"
    with rasterio.open(
        str(rotated),
        "w",
        driver="GTiff",
        height=SIZE,
        width=SIZE,
        count=1,
        dtype="float64",
        crs=CRS,
        transform=Affine(CELL, 5.0, XMIN, 5.0, -CELL, YMAX),
        nodata=NODATA,
    ) as sink:
        sink.write(_elevation(), 1)
    job = _staged(
        tmp_path, _request(tmp_path, inputs={"dem": {"href": str(rotated)}, "mask": None})
    )

    outcome = run(job, exit_code_for=exit_code_for)

    assert outcome.status == "failed"
    assert outcome.exit_code == EXIT_VALIDATION
    assert "rotated or sheared transform" in outcome.errors[0]["detail"]


def test_a_terrain_of_several_bands_is_read_on_band_one_and_says_so(tmp_path):
    """Accepted, because a DEM shipped as band 1 of a stack is legitimate, and
    warned about, because the other bands are silently ignored."""
    stacked = tmp_path / "stacked.tif"
    with rasterio.open(
        str(stacked),
        "w",
        driver="GTiff",
        height=SIZE,
        width=SIZE,
        count=3,
        dtype="float64",
        crs=CRS,
        transform=rasterio.transform.from_origin(XMIN, YMAX, CELL, CELL),
        nodata=NODATA,
    ) as sink:
        sink.write(_elevation(), 1)
        sink.write(np.zeros((SIZE, SIZE)), 2)
        sink.write(np.zeros((SIZE, SIZE)), 3)
    job = _staged(tmp_path, _request(tmp_path, inputs={"dem": {"href": str(stacked)}}))

    outcome = run(job, exit_code_for=exit_code_for)

    assert outcome.status == "successful", outcome.errors
    assert any("band 1 is read" in warning for warning in outcome.warnings)
    active = _band(job, ACTIVE_CELLS_PATH).astype(bool)
    np.testing.assert_allclose(_band(job, BOTTOM_PATH)[active], _elevation()[active] - THICKNESS)
