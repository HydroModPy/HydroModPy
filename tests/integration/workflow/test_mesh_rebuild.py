"""A resume reloads the mesh it generated instead of generating another one.

Gmsh is not reproducible run to run - the measured evidence is in
:mod:`hydromodpy.mesh.cache`. A resume that re-meshes therefore
does not repeat the step's work, it changes the mesh every number downstream is
computed on, and the run that comes back from the crash is not the run that
went into it.

The mesh of a generated request lives under ``<project>/.hmp/mesh_cache/``. The
``triangle`` engine is the one to resume: the ``voronoi`` engine draws its seeds from
the request seed, is reproducible, and asks for no cache. The
run below crashes after the mesh is complete, then resumes in a context that
knows nothing, with the engine itself replaced by a bomb.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

try:
    import gmsh  # noqa: F401
except (ImportError, OSError) as exc:
    pytest.skip(f"could not import 'gmsh': {exc}", allow_module_level=True)

REPO_ROOT = Path(__file__).resolve().parents[3]
DEM = REPO_ROOT / "examples" / "data" / "dem" / "regional_dem_naizin.tif"

RUN_NAME = "meshed_then_crashed"

PROJECT_TOML = """
[workflow]
mode = "simulation"

[site]
name = "naizin"

[simulation]
name = "naizin_mesh_rebuild"

[[simulation.process]]
id = "flow"
kind = "flow"
solvers = ["modflow6"]

[workspace]

[geographic]
crs_project = "EPSG:2154"
dem_correc_type = "breach"

[geographic.catchment]
kind = "from_outlet_coord"
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

[mesh]
engine = "triangle"
cell_size = 350.0

[mesh.families]
geology = "none"

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
kind = "custom"
value = "5.0 m"

[domain.layers]
nlay = 1

[display]
enabled = false
"""


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _cached_arrays(root: Path) -> Path:
    """Return the one cached mesh of the project."""
    from hydromodpy.mesh.cache import ARRAYS_FILENAME

    found = sorted((root / ".hmp" / "mesh_cache").glob(f"*/{ARRAYS_FILENAME}"))
    assert len(found) == 1, f"expected one cached mesh, found {found}"
    return found[0]


def _journal_row(root: Path, run_id: str, step_order: int):
    from hydromodpy.core.state.result_dirs import run_dir_rel
    from hydromodpy.workflow.record.journal import WorkflowJournal

    rows = WorkflowJournal(root / run_dir_rel(run_id)).list_steps(run_id)
    return next(row for row in rows if row.step_order == step_order)


@pytest.fixture(scope="module")
def meshed_then_crashed(tmp_path_factory: pytest.TempPathFactory):
    """Mesh a real catchment, then crash in ``setup_process``.

    The crash lands after ``build_mesh`` completed, which is the case a resume
    must not re-mesh. The window stops at ``setup_process`` so no solver binary
    is needed.
    """
    if not DEM.is_file():
        pytest.skip(f"missing DEM fixture {DEM}")
    from hydromodpy.core.exceptions import StepError
    from hydromodpy.project.facade import Project
    from hydromodpy.workflow.steps.setup import SetupProcessStep

    root = tmp_path_factory.mktemp("mesh_rebuild")
    config_path = root / "project.toml"
    config_path.write_text(
        PROJECT_TOML.format(root=root.as_posix(), dem=DEM.as_posix()),
        encoding="utf-8",
    )

    def _bomb(_self, _state):
        raise RuntimeError("injected crash in setup_process")

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(SetupProcessStep, "run", _bomb)
        project = Project(config_path, no_display=True)
        try:
            with pytest.raises(StepError, match="injected crash in setup_process"):
                project.simulate(name=RUN_NAME, until_step="setup_process")
        finally:
            project.close()

    row = _journal_row(root, RUN_NAME, 4)
    return root, row, _digest(_cached_arrays(root))


def test_the_step_declares_the_mesh_it_left(meshed_then_crashed) -> None:
    """The journal carries a real digest over the cached mesh, not the empty one."""
    from hydromodpy.mesh.cache import ARRAYS_FILENAME, DESCRIPTION_FILENAME

    root, row, _arrays_digest = meshed_then_crashed

    assert row.step_name == "build_mesh"
    assert row.status == "completed"
    assert row.artifact_uris, "build_mesh declares nothing after meshing a catchment"
    names = {Path(uri).name for uri in row.artifact_uris}
    assert names == {ARRAYS_FILENAME, DESCRIPTION_FILENAME}
    assert all((root / uri).exists() for uri in row.artifact_uris)
    assert row.outputs_hash != hashlib.sha256(b"").hexdigest()


def test_a_resume_reloads_the_mesh_instead_of_generating_another(
    meshed_then_crashed,
) -> None:
    """The engine is a bomb: reaching it at all is the failure."""
    from hydromodpy.mesh import registry
    from hydromodpy.mesh.engines.triangle.engine import TriangleMeshEngine
    from hydromodpy.project.facade import Project

    root, _row, arrays_digest = meshed_then_crashed

    def _bomb(*_args, **_kwargs):
        raise AssertionError("the resume regenerated the mesh")

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(TriangleMeshEngine, "build", _bomb)
        assert registry.mesh_engines.get("triangle") is TriangleMeshEngine
        project = Project(root / "project.toml", no_display=True)
        try:
            project.simulate(resume=RUN_NAME, until_step="setup_process")
            setup = project._ctx.setup
            assert setup.cell_mesh is not None, "the resume loaded no mesh"
            assert setup.cell_mesh.identity.engine_id == "triangle"
            assert setup.mesh_summary["cache_key"] is not None
        finally:
            project.close()

    assert _digest(_cached_arrays(root)) == arrays_digest
