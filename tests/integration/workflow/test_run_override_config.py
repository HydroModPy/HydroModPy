"""An override defines the run's configuration, so every builder reads it.

``Project.simulate(thickness=...)`` used to patch the built ``Domain`` after the
fact. The domain is built from ``cfg.domain`` by every path that builds it, and
a resume reconstructs the prefix in another process: ``run_setup`` rebuilt the
domain from the bare configuration and the override was gone, silently, while
an override of a flow parameter survived the same resume because ``ensure_flow``
happens to keep an object it finds. The configuration the run archived beside
its results described a run that never happened.

The run below is launched with an override, closed, and resumed from a fresh
session. Before the change the resumed domain came back at the declared 50 m.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
DEM = REPO_ROOT / "examples" / "data" / "dem" / "regional_dem_naizin.tif"

RUN_NAME = "thick_probe"
DECLARED_THICKNESS = 50.0
OVERRIDDEN_THICKNESS = 99.0

PROJECT_TOML = """
[workflow]
mode = "simulation"

[simulation]
name = "naizin_override"

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


def _thickness_of(project) -> float:
    return float(project._ctx.setup.domain.config.depth_model.thickness)


@pytest.fixture(scope="module")
def launched_with_an_override(tmp_path_factory: pytest.TempPathFactory):
    """Run the head of a project with ``thickness=99``, then close the session.

    The window stops at ``setup_process``: it is the first step consuming the
    model phase, so the run owns a workspace and a journal, and needs no solver
    binary.
    """
    if not DEM.is_file():
        pytest.skip(f"missing DEM fixture {DEM}")
    from hydromodpy.project.facade import Project

    root = tmp_path_factory.mktemp("run_override")
    config_path = root / "project.toml"
    config_path.write_text(
        PROJECT_TOML.format(root=root.as_posix(), dem=DEM.as_posix()),
        encoding="utf-8",
    )

    project = Project(config_path, no_display=True)
    try:
        project.simulate(
            name=RUN_NAME,
            thickness=OVERRIDDEN_THICKNESS,
            until_step="setup_process",
        )
        built = _thickness_of(project)
    finally:
        project.close()

    return root, built


def test_the_run_builds_the_domain_the_override_asks_for(launched_with_an_override) -> None:
    """The obvious half, and the one that already worked."""
    _root, built = launched_with_an_override

    assert built == OVERRIDDEN_THICKNESS


def test_the_run_archives_the_configuration_it_was_launched_on(
    launched_with_an_override,
) -> None:
    """The resolved configuration a checkpoint signs names the overridden value.

    It used to name the declared 50 m, so the only on-disk description of an
    override run could not reproduce it.
    """
    from hydromodpy.workflow.internals.manifest import read_resolved_config

    root, _built = launched_with_an_override

    payload = read_resolved_config(root, RUN_NAME)

    assert payload is not None
    assert payload["domain"]["depth_model"]["thickness"] == OVERRIDDEN_THICKNESS


def test_a_resume_repeating_the_override_keeps_it(launched_with_an_override) -> None:
    """The prefix reconstruction builds the run's domain, not the declared one.

    This is the measurement of D168: the resumed domain came back at 50 m.
    """
    from hydromodpy.project.facade import Project

    root, _built = launched_with_an_override

    project = Project(root / "project.toml", no_display=True)
    try:
        project.simulate(
            resume=RUN_NAME,
            thickness=OVERRIDDEN_THICKNESS,
            until_step="setup_process",
        )
        resumed = _thickness_of(project)
    finally:
        project.close()

    assert resumed == OVERRIDDEN_THICKNESS


def test_a_resume_dropping_the_override_is_refused_by_name(
    launched_with_an_override,
) -> None:
    """Asking to continue the run under another configuration is refused.

    Silently building a 50 m domain on top of a prefix computed at 99 m was the
    defect. The override is part of what defines this run, so a resume that
    drops it is a different run, and the refusal says which section moved.
    """
    from hydromodpy.core.exceptions import ResumeError
    from hydromodpy.project.facade import Project

    root, _built = launched_with_an_override

    project = Project(root / "project.toml", no_display=True)
    try:
        with pytest.raises(ResumeError, match="domain"):
            project.simulate(resume=RUN_NAME, until_step="setup_process")
    finally:
        project.close()


def test_a_second_override_on_the_same_project_rebuilds_the_domain(
    launched_with_an_override,
) -> None:
    """A Project builds its model phase once; each run still gets its geometry.

    ``sweep`` drives one live Project through N values. The domain must follow
    the configuration of the run, not stay on the one that built the phase.
    """
    from hydromodpy.project.facade import Project

    root, _built = launched_with_an_override

    project = Project(root / "project.toml", no_display=True)
    try:
        project.simulate(name="probe_70", thickness=70.0, until_step="setup_process")
        first = _thickness_of(project)
        project.simulate(name="probe_120", thickness=120.0, until_step="setup_process")
        second = _thickness_of(project)
    finally:
        project.close()

    assert (first, second) == (70.0, 120.0)


def test_a_plain_run_after_an_override_goes_back_to_the_declared_domain(
    launched_with_an_override,
) -> None:
    """The overridden geometry belongs to the run that asked for it.

    The next run of the same session declares 50 m, archives 50 m, and must not
    silently keep the 99 m domain the previous one left on the context.
    """
    from hydromodpy.project.facade import Project

    root, _built = launched_with_an_override

    project = Project(root / "project.toml", no_display=True)
    try:
        project.simulate(name="overridden", thickness=99.0, until_step="setup_process")
        overridden = _thickness_of(project)
        project.simulate(name="plain", until_step="setup_process")
        plain = _thickness_of(project)
    finally:
        project.close()

    assert (overridden, plain) == (OVERRIDDEN_THICKNESS, DECLARED_THICKNESS)


def test_a_dry_run_leaves_the_context_on_the_declared_configuration(
    launched_with_an_override,
) -> None:
    """A preview executes nothing, so it defines no run and resolves no config."""
    from hydromodpy.project.facade import Project

    root, _built = launched_with_an_override

    project = Project(root / "project.toml", no_display=True)
    try:
        project.simulate(name="preview", thickness=99.0, dry_run=True)
        assert project._ctx.cfg is project._cfg
    finally:
        project.close()
