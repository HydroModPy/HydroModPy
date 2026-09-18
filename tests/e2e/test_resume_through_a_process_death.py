"""The exit gate of F7: a resume across a real process death.

Every other resume test in the suite raises an exception inside the pipeline.
That leaves the process alive: handlers run, the catalog closes, DuckDB folds
its journal into the database file. None of that happens when a machine loses
power, the OOM killer fires, or a scheduler cancels a job - and those are the
deaths a resume exists for.

Here the child sends itself ``SIGKILL``, twice. Nothing is caught, nothing is
flushed, and the next process starts from what the disk holds.

What the runs prove, together:

- the project index of a killed run can be opened again at all (it could not
  until the migration runner stopped leaving its schema in the journal);
- the journal names the step that was running when the process died;
- the resume re-reads the delineation instead of re-running it - the 46 files
  it declared are identical, bytes and modification times, and its journal row
  keeps the ``started_at`` of the run that died;
- the mesh the resumed run generated survives the second death and is not
  regenerated - Gmsh is not reproducible run to run, so a resume that re-meshes
  silently changes every number computed downstream;
- the domain that comes out is the domain of an uninterrupted run, array for
  array.

The driver goes through ``Project.simulate``, which is what ``hmp run`` and
``hmp run --resume`` call. The window stops at ``setup_process``: it is the
first step that consumes the model phase, and it needs no solver binary.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("whitebox_workflows")

REPO_ROOT = Path(__file__).resolve().parents[2]
DEM = REPO_ROOT / "examples" / "data" / "dem" / "regional_dem_naizin.tif"

RUN_NAME = "killed_twice"
REFERENCE_RUN = "uninterrupted"

PROJECT_TOML = """
[workflow]
mode = "simulation"

[simulation]
name = "naizin_process_death"

[[simulation.process]]
id = "flow"
type = "flow"
solvers = ["modflow_nwt"]

[workspace]
project_root = "{root}"

[geographic]
crs_project = "EPSG:2154"
dem_correc_type = "breach"

[geographic.catchment]
catch_def = "from_outlet_coord"
dem_init_path = "{dem}"
x_outlet = 265611.933
y_outlet = 6784182.776
snap_dist = "50 m"
buff_area = "20%"

[geographic.river_network]
enabled = true
threshold_mode = "area_km2"
threshold_area_km2 = 1.0
prune_short_streams = false
compute_strahler_order = true
compute_stream_links = true
all_vertices = true

[mesh_catchment]
constraints_mode = "rivers_only"
output_layout = "flat"
figures_enabled = false

[mesh_catchment.zone_meshing]
global_size = 350.0
min_size = 150.0
max_size = 800.0

[domain]

[domain.depth_model]
kind = "constant_thickness"
thickness = "50.0 m"

[data]
types = ["recharge"]
inference_mode = "warn"

[[data.recharge.sources]]
source = "synthetic"
values = [3.0]
runoff_ratio = 0.0

[flow]
flow_regime = "steady"
active_sinks_sources = ["recharge"]
active_bc = ["drainage"]
param_list = ["K"]

[flow.param.K.field]
id = "K"
kind = "homogeneous"
value = "1e-5 m/s"

[flow.ic]
type = "custom"
value = "5.0 m"

[modflownwt.sgrid.planar]
mode = "keep_native"

[modflownwt.sgrid.vertical]
nlay = 1

[display]
enabled = false
"""

# Runs one window in a process of its own, optionally killing that process at
# the entry of a named step, and digests the runtime it ends up holding.
_DRIVER = """
import hashlib
import json
import os
import signal
import sys
from pathlib import Path

config, run_name, mode, kill_at, digest_path = sys.argv[1:6]


def _die(*_args, **_kwargs):
    os.kill(os.getpid(), signal.SIGKILL)


if kill_at == "build_mesh":
    import hydromodpy.workflow.steps.mesh as mesh_module

    mesh_module.step_mesh = _die
elif kill_at == "setup_process":
    from hydromodpy.workflow.steps.setup import SetupProcessStep

    SetupProcessStep.run = _die

import numpy as np

from hydromodpy.project.facade import Project
from hydromodpy.spatial.geographic.artifacts import geographic_artifact_paths


def _array_digest(values):
    array = np.ascontiguousarray(values)
    return {
        "sha256": hashlib.sha256(array.tobytes()).hexdigest(),
        "shape": list(array.shape),
        "dtype": str(array.dtype),
    }


def _surface_digest(surface):
    if surface is None:
        return None
    return _array_digest(np.asarray(surface.as_array(), dtype="float64"))


def _zone_digest(zone):
    for reader in ("encoded_codes", "as_array", "values"):
        candidate = getattr(zone, reader, None)
        if callable(candidate):
            candidate = candidate()
        if candidate is None:
            continue
        try:
            return _array_digest(candidate)
        except (TypeError, ValueError):
            continue
    raise AssertionError(f"no array to digest in zone {type(zone).__name__}")


project = Project(config, no_display=True)
try:
    if mode == "fresh":
        project.simulate(name=run_name, until_step="setup_process")
    else:
        project.simulate(resume=run_name, until_step="setup_process")
    setup = project._ctx.setup
    domain = setup.domain
    payload = {
        "domain": {
            "surface_topo": _surface_digest(domain.surface_topo),
            "substratum": _surface_digest(domain.substratum),
            "georeferencing": hashlib.sha256(
                json.dumps(domain.georeferencing, sort_keys=True, default=str).encode()
            ).hexdigest(),
            "z_interfaces": [float(value) for value in domain.z_interfaces],
            "zones": {key: _zone_digest(value) for key, value in sorted(domain.zones.items())},
        },
        "declared_geographic_files": sorted(
            str(path) for path in geographic_artifact_paths(setup.geographic)
        ),
        "mesh_loaded": setup.mesh_planar is not None and setup.mesh_bundle is not None,
    }
    Path(digest_path).write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
finally:
    project.close()
"""

# Reads the workflow journal of a run in a process that shares nothing with the
# one that wrote it.
_JOURNAL_READER = """
import json
import sys
from pathlib import Path

from hydromodpy.results.catalog import Catalog
from hydromodpy.workflow.tracking.journal import WorkflowJournal

catalog = Catalog(Path(sys.argv[1]))
try:
    rows = [
        {
            "order": row.step_order,
            "name": row.step_name,
            "status": row.status,
            "started_at": str(getattr(row, "started_at", "")),
            "artifact_uris": list(row.artifact_uris or ()),
        }
        for row in WorkflowJournal(catalog).list_steps(sys.argv[2])
    ]
finally:
    catalog.close()
print(json.dumps(rows))
"""


def _project_at(root: Path) -> Path:
    config = root / "project.toml"
    config.write_text(
        PROJECT_TOML.format(root=root.as_posix(), dem=DEM.as_posix()),
        encoding="utf-8",
    )
    return config


def _drive(
    root: Path,
    run_name: str,
    mode: str,
    *,
    kill_at: str = "",
    digest: Path | None = None,
) -> int:
    """Run one window in a child process and return its exit code."""
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            _DRIVER,
            str(root / "project.toml"),
            run_name,
            mode,
            kill_at,
            "" if digest is None else str(digest),
        ],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=900,
        check=False,
    )
    if completed.returncode not in (0, -9):
        pytest.fail(
            f"the {mode} run exited {completed.returncode}\n"
            f"stdout: {completed.stdout[-2000:]}\nstderr: {completed.stderr[-4000:]}"
        )
    return completed.returncode


def _journal(root: Path, run_name: str) -> list[dict]:
    completed = subprocess.run(
        [sys.executable, "-c", _JOURNAL_READER, str(root), run_name],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    if completed.returncode != 0:
        pytest.fail(
            f"the index of a killed run could not be opened\nstderr: {completed.stderr[-4000:]}"
        )
    return json.loads(completed.stdout.strip().splitlines()[-1])


def _marks(paths: list[Path]) -> dict[str, tuple[str, int]]:
    """Digest and modification time of every file that exists, by name."""
    return {
        str(path): (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns)
        for path in paths
        if path.is_file()
    }


def _mesh_marks(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted((root / "mesh").rglob("*"))
        if path.is_file()
    }


@pytest.fixture(scope="module")
def uninterrupted(tmp_path_factory: pytest.TempPathFactory) -> dict:
    """One complete run, nothing interrupted, as the reference to reproduce."""
    if not DEM.is_file():
        pytest.skip(f"missing DEM fixture {DEM}")
    root = tmp_path_factory.mktemp("uninterrupted")
    _project_at(root)
    digest = root / "digest.json"

    assert _drive(root, REFERENCE_RUN, "fresh", digest=digest) == 0

    return json.loads(digest.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def killed_twice(tmp_path_factory: pytest.TempPathFactory) -> dict:
    """Die inside ``build_mesh``, resume and die inside ``setup_process``, resume.

    The second death lands after the meshing completed, which is the moment a
    resume must not re-mesh. The third run is an ordinary resume with nothing
    patched at all.
    """
    if not DEM.is_file():
        pytest.skip(f"missing DEM fixture {DEM}")
    root = tmp_path_factory.mktemp("killed_twice")
    _project_at(root)

    first_death = _drive(root, RUN_NAME, "fresh", kill_at="build_mesh")
    journal_after_first = _journal(root, RUN_NAME)
    declared = [
        root / uri
        for row in journal_after_first
        if row["name"] == "build_geographic"
        for uri in row["artifact_uris"]
    ]
    delineation_after_first = _marks(declared)

    second_death = _drive(root, RUN_NAME, "resume", kill_at="setup_process")
    journal_after_second = _journal(root, RUN_NAME)
    delineation_after_second = _marks(declared)
    mesh_after_second = _mesh_marks(root)

    digest = root / "digest.json"
    final = _drive(root, RUN_NAME, "resume", digest=digest)

    return {
        "root": root,
        "exit_codes": (first_death, second_death, final),
        "journal_after_first": journal_after_first,
        "journal_after_second": journal_after_second,
        "journal_after_final": _journal(root, RUN_NAME),
        "delineation_after_first": delineation_after_first,
        "delineation_after_second": delineation_after_second,
        "mesh_after_second": mesh_after_second,
        "mesh_final": _mesh_marks(root),
        "digest": json.loads(digest.read_text(encoding="utf-8")),
    }


def test_the_two_deaths_are_uncatchable_and_the_last_run_completes(killed_twice) -> None:
    """``-9`` is SIGKILL: no handler ran, nothing was flushed on the way out."""
    assert killed_twice["exit_codes"] == (-9, -9, 0)


def test_the_index_of_a_killed_run_is_readable_by_the_next_process(killed_twice) -> None:
    """The journal names the step that was running when the process died.

    ``failed`` is what an exception leaves. A killed process writes nothing on
    its way out, so the row stays ``running`` - and that is the state a resume
    has to be able to read.
    """
    rows = [
        (row["order"], row["name"], row["status"]) for row in killed_twice["journal_after_first"]
    ]

    assert rows == [
        (0, "validate", "completed"),
        (1, "resolve", "completed"),
        (2, "build_geographic", "completed"),
        (3, "load_data", "completed"),
        (4, "build_mesh", "running"),
    ]


def test_the_resume_reads_the_delineation_instead_of_running_it_again(killed_twice) -> None:
    """Same bytes and same modification times, file by file."""
    before = killed_twice["delineation_after_first"]
    after = killed_twice["delineation_after_second"]

    assert before, "the crashed run declared no geographic artifact to compare"
    assert after == before

    build_geographic = next(
        row for row in killed_twice["journal_after_final"] if row["name"] == "build_geographic"
    )
    original = next(
        row for row in killed_twice["journal_after_first"] if row["name"] == "build_geographic"
    )

    assert build_geographic["started_at"] == original["started_at"]


def test_the_mesh_survives_the_second_death_and_is_not_generated_again(killed_twice) -> None:
    """Gmsh is not reproducible, so a regenerated mesh is a different model."""
    assert killed_twice["mesh_after_second"], "the resumed run left no mesh behind"
    assert killed_twice["mesh_final"] == killed_twice["mesh_after_second"]
    assert killed_twice["digest"]["mesh_loaded"]


def test_the_window_finishes_and_every_step_is_journalled(killed_twice) -> None:
    """Six steps, all completed, after two processes died inside them."""
    rows = [
        (row["order"], row["name"], row["status"]) for row in killed_twice["journal_after_final"]
    ]

    assert rows == [
        (0, "validate", "completed"),
        (1, "resolve", "completed"),
        (2, "build_geographic", "completed"),
        (3, "load_data", "completed"),
        (4, "build_mesh", "completed"),
        (5, "setup_process", "completed"),
    ]


def test_the_domain_that_comes_back_is_the_domain_of_an_uninterrupted_run(
    killed_twice, uninterrupted
) -> None:
    """Surface, substratum, zones, georeferencing and interfaces, all identical.

    The domain is rebuilt from the DEM at every process start, so this says the
    two deaths changed no number, not that anything was skipped. What was
    skipped is asserted on the files themselves, above.
    """
    assert killed_twice["digest"]["domain"] == uninterrupted["domain"]
