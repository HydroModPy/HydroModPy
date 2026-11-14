"""The lab plays the steps of a run in memory, one by one, and keeps no run until asked.

A small MODFLOW 6 island with a well is built once, and each test starts from it.
"""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

import numpy as np
import pytest

import hydromodpy as hmp
from hydromodpy.core.config_kit.written import written_payload
from hydromodpy.core.exceptions import CommandUsageError, ConfigError
from hydromodpy.core.state.scratch import scratch_root_for
from tests.scenarios.factory import LAKE_WELL, TRANSIENT, write_project
from tests.scenarios.launcher import isolated_env, link_binaries

pytestmark = [
    pytest.mark.mf6,
    pytest.mark.binary,
    pytest.mark.allow_subprocess,
    pytest.mark.xdist_group(name="lab"),
]

CREST = "geographic.synthetic.topography.crest_elevation"
FLOOR = "domain.depth_model.substratum_elevation"
BASE = {"K": "5e-6 m/s", FLOOR: -5.0, CREST: 12.0}
WELL_CELL = "hydromodpy/solver/modflow6/builders/wells.py:resolve_well_disv_cell"
BUILD = "hydromodpy/solver/modflow6/adapter.py:Modflow6FlowAdapter.build"


@pytest.fixture(scope="module")
def island(tmp_path_factory: pytest.TempPathFactory):
    """Write the island and give its TOML path, with a throwaway HOME and cache."""
    root = tmp_path_factory.mktemp("lab")
    text = TRANSIENT.replace("@NAME@", "island").replace("@SOLVER@", "modflow6")
    write_project(
        root / "project", {"island.toml": text.replace("@TRANSPORT_PROCESS@", "") + LAKE_WELL}
    )
    link_binaries(root / "cache", ("mf6", "libmf6.so"))
    env = isolated_env(root / "home", root / "cache", root / "state", root / "tmp")
    with pytest.MonkeyPatch.context() as patch:
        for key in ("HOME", "HMP_CACHE_HOME", "HMP_STATE_HOME", "HMP_NO_PROGRESS", "TZ"):
            patch.setenv(key, env[key])
        yield root / "project" / "island.toml"


@pytest.fixture(scope="module")
def played(island: Path):
    """The lab of the island, built through run_solver once."""
    with hmp.Lab(island) as lab:
        lab.solve()
        yield lab


@pytest.fixture
def lab(played):
    """The built lab, reset to the file and with nothing forced."""
    for name in list(played._forced):
        played.release(name)
    played.set(BASE)
    played.solve()
    return played


def _seconds(lab) -> dict[str, float]:
    return dict(zip(lab.steps.step, lab.steps.seconds, strict=True))


def _bump_k(lab, value: float) -> None:
    lab.set(K=value)
    lab.solve()


def test_advance_fills_the_state_one_step_at_a_time(island: Path):
    with hmp.Lab(island) as fresh:
        assert set(fresh.steps.status) == {"pending"}
        assert fresh.advance("build_geographic").mesh is None
        assert fresh.state.geographic is not None and fresh.state.domain is not None
        assert fresh.advance("build_mesh").mesh.n_cells > 0
        status = dict(zip(fresh.steps.step, fresh.steps.status, strict=True))
        assert (status["build_mesh"], status["setup_process"]) == ("built", "pending")
        assert not (island.parent / "runs").exists()


def test_a_solve_with_nothing_changed_plays_no_step(lab):
    before = _seconds(lab)
    assert lab.set(K="5e-6 m/s") == ()
    lab.solve()
    assert _seconds(lab) == pytest.approx(before, nan_ok=True)


@pytest.mark.parametrize(
    ("change", "first_stale"),
    [
        ({"K": 2e-5}, "prepare_solver"),
        ({FLOOR: -8.0}, "setup_process"),
        ({CREST: 14.0}, "build_geographic"),
    ],
)
def test_a_change_makes_stale_the_steps_from_the_first_that_reads_it(lab, change, first_stale):
    stale = lab.set(change)
    names = list(lab.steps.step)
    assert stale[0] == first_stale
    assert stale == tuple(names[names.index(first_stale) : names.index("run_solver") + 1])
    assert set(lab.steps.status[lab.steps.step.isin(stale)]) == {"stale"}


def test_a_whole_section_is_compared_key_by_key(lab):
    from copy import deepcopy

    from hydromodpy.core.config_kit.written import written_payload

    section = deepcopy(written_payload(lab.config)["geographic"])
    assert lab.set(geographic=section) == ()
    section = deepcopy(section)
    section["synthetic"]["topography"]["crest_elevation"] = 14.0
    assert lab.set(geographic=section)[0] == "build_geographic"


@pytest.mark.parametrize(
    ("changes", "refusal"),
    [({"Kzz": 1}, "Unknown parameter 'Kzz'"), ({"metrics": {}}, "no pipeline step reads")],
)
def test_a_refused_change_leaves_the_lab_as_it_was(lab, changes, refusal):
    before, steps = lab.config, list(lab.steps.status)
    with pytest.raises(ConfigError, match=refusal):
        lab.set(changes)
    assert (lab.config, list(lab.steps.status)) == (before, steps)


def test_a_forced_model_survives_a_set_until_it_is_released(lab):
    model = lab.state.model
    forced = model.with_properties(K=np.full(model.geometry.cells.n_cells, 1e-5))
    lab.force("model", forced)
    prepared = _seconds(lab)["prepare_solver"]
    lab.solve()
    assert _seconds(lab)["prepare_solver"] == prepared
    assert list(lab.steps.forced[lab.steps.step == "prepare_solver"])[0] == ("model",)
    lab.set(Sy=0.02)
    lab.solve()
    assert lab.state.model.properties.overrides.keys() == {"K"}
    lab.release("model")
    lab.solve()
    assert lab.state.model is not forced


def test_a_forced_flow_survives_a_set_until_it_is_released(lab):
    flow = lab.state.flow
    lab.force("flow", flow)
    lab.set(K=2e-5)
    lab.solve()
    assert lab.state.flow is flow
    lab.release("flow")
    lab.solve()
    assert lab.state.flow is not flow


def test_released_data_is_loaded_again(lab):
    lab.force("data", lab.state.data)
    lab.release("data")
    assert lab.solve()


def test_a_name_that_is_not_forced_cannot_be_released_or_forced(lab):
    with pytest.raises(CommandUsageError, match="not forced"):
        lab.release("mesh")
    with pytest.raises(CommandUsageError, match="cannot force"):
        lab.force("plan", None)


def test_a_run_is_refused_while_an_object_is_forced(lab, island: Path):
    lab.force("model", lab.state.model)
    with pytest.raises(CommandUsageError, match="model is forced"):
        lab.run("x")
    assert not (island.parent / "runs").exists()


def test_a_step_after_run_solver_is_refused_to_advance(lab):
    with pytest.raises(CommandUsageError, match="belongs to a run"):
        lab.advance("extract")


def test_capture_records_a_function_and_a_method_the_project_crosses(lab):
    _bump_k(lab, 3e-5)
    with lab.capture(WELL_CELL, BUILD) as seen:
        _bump_k(lab, 4e-5)
    (well,) = seen[WELL_CELL]
    assert (well["locals"]["well_id"], well["returned"][0]) == ("W1", 0)
    (build,) = seen[BUILD]
    assert build["locals"]["model"] is lab.state.model


def test_capture_gives_back_the_profile_hook_when_the_block_raises(lab):
    before = sys.getprofile()
    with pytest.raises(RuntimeError, match="boom"), lab.capture(WELL_CELL):
        raise RuntimeError("boom")
    assert sys.getprofile() is before


def test_a_build_only_solve_builds_the_flow_runs_and_solves_none(island: Path):
    scratch = scratch_root_for(island.parent)
    others = set(scratch.glob("lab_*"))
    with hmp.Lab(island) as fresh:
        built = fresh.solve(build_only=True)
        assert built and not any(run.solved for run in built.values())
        assert fresh.state.solves == {}
        assert all(run.solved for run in fresh.solve(built).values())
        fresh.set(K=2e-5)
        with pytest.raises(CommandUsageError, match="model changed"):
            fresh.solve(built)
    assert set(scratch.glob("lab_*")) == others


def test_the_written_config_is_read_back_without_an_error(lab, tmp_path: Path):
    lab.set(K=2e-5)
    path = lab.write_config(tmp_path / "lab.toml")
    assert [d for d in hmp.check(path) if "error" in str(d.severity).lower()] == []
    assert "2e-05" in path.read_text(encoding="utf-8").lower() or "2e-5" in path.read_text("utf-8")


def test_the_lab_walks_from_a_file_to_a_kept_run(island: Path, tmp_path: Path):
    # [lab-walkthrough]
    lab = hmp.Lab(island)  # opens the project, builds nothing
    lab.advance("build_mesh")  # plays validate to build_mesh in memory
    cells = lab.state.mesh.n_cells  # the objects of the engine, by name
    stale = lab.set(K=2e-5)  # a change returns the built steps it made stale
    assert stale == ()  # nothing was built after the mesh yet
    results = lab.solve()  # plays what is missing, up to run_solver
    lab.set(K=3e-5)
    assert lab.steps.status[lab.steps.step == "run_solver"].item() == "stale"
    lab.force("model", lab.state.model)  # keep this model, whatever the file says
    assert lab.steps.forced[lab.steps.step == "prepare_solver"].item() == ("model",)
    lab.release("model")  # the model is built from the configuration again
    with lab.capture(WELL_CELL) as seen:  # watch a function the solve crosses
        lab.solve()
    well = seen[WELL_CELL][0]["locals"]["well_id"]
    written = lab.write_config(tmp_path / "lab.toml")  # the file of what the lab holds
    # [/lab-walkthrough]
    assert (cells, well, written.is_file()) == (cells, "W1", True)
    assert results and not (island.parent / "runs").exists()
    lab.close()


@pytest.fixture
def island_doc(island: Path) -> dict:
    """The sections of the island."""
    import tomllib

    return tomllib.loads(island.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    ("act", "refusal"),
    [
        (lambda lab, path: lab.advance("run_solver"), r"setup_process reads \[simulation\]"),
        (lambda lab, path: lab.run("draft"), "so lab.run cannot keep it"),
        (lambda lab, path: lab.write_config(path), "so lab.write_config cannot keep it"),
        (lambda lab, path: lab.project.simulate(name="draft"), "is a draft"),
        (lambda lab, path: hmp.Project(lab.config).simulate(name="draft"), "is a draft"),
    ],
)
def test_a_draft_refuses_what_needs_a_section_it_lacks(island, island_doc, tmp_path, act, refusal):
    del island_doc["simulation"]
    with hmp.Lab(island_doc, base=island.parent) as draft:
        with pytest.raises(ConfigError, match=refusal):
            act(draft, tmp_path / "draft.toml")
        assert not (island.parent / "runs" / "draft").exists()


def test_a_lab_of_a_dict_reads_an_old_key_as_a_project_does(island: Path, island_doc):
    from tests.scenarios.factory import OLDER_SOLVER_TABLES

    island_doc.update(tomllib.loads(OLDER_SOLVER_TABLES))
    with hmp.Lab(island_doc, base=island.parent) as lab:
        assert written_payload(lab.config) == written_payload(
            hmp.Project(island_doc, base=island.parent)._cfg
        )


def test_a_lab_of_a_dict_refuses_a_file_key_as_a_project_does(island: Path, island_doc):
    island_doc["base_config"] = "nothing.toml"
    with pytest.raises(ConfigError, match="base_config is a key of a TOML file"):
        hmp.Lab(island_doc, base=island.parent)


def test_a_lab_of_a_file_refuses_a_path_no_step_reads(lab):
    with pytest.raises(ConfigError, match=r"no pipeline step reads site\.name"):
        lab.set({"site.name": "elsewhere"})


def test_a_draft_built_section_after_section_solves_its_file(island: Path, island_doc, played):
    first = {k: island_doc[k] for k in ("geographic", "data")}
    with hmp.Lab(first, base=island.parent) as lab:
        assert lab.advance("build_geographic").geographic is not None
        rest = {k: island_doc[k] for k in ("domain", "flow", "simulation", "site")}
        assert lab.set(**rest)[-1] == "build_geographic"
        assert "built" not in set(lab.steps.status)
        assert lab.advance("build_mesh").mesh.n_cells == played.state.mesh.n_cells
        solves = lab.solve()
        assert [run.solved for run in solves.values()] == [True]
        assert list(lab.state.plan.runs) == list(played.state.plan.runs)
        assert set(lab.steps.status[: lab.steps.step.tolist().index("run_solver") + 1]) == {"built"}
