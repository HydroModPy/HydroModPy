"""The harness without a solver run: the factory, the environment and the launcher."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from tests.scenarios.factory import (
    ISLAND_VARIANTS,
    files_digest,
    island_files,
    tree_digest,
    write_project,
)
from tests.scenarios.launcher import (
    Scenario,
    find_targets,
    isolated_env,
    link_binaries,
    play,
)

pytestmark = pytest.mark.fast

# Digests of the five islands, as the reference projects wrote them. A change of
# a project text changes its digest, so this table is edited with the text.
ISLAND_DIGESTS = {
    "gwt": "564d23dabf206abbe4a5d786cd3ef5521968122877c1ead2a8323f586a8fe252",
    "nwt": "d93022dea0dacf8c57f1838d15f321f7b1950303127bb47ad02185c0baae4c63",
    "boussinesq": "c0fd06b0f86b1bdf39064ae0348afd6efaa5bbdd00c816d8320c088f74deb1ae",
    "spinup": "b3af4af7302006e817dd40a458fdd92c9e6d605ef805325a4a2cb81cbb7beb07",
    "calage": "04db3c90b65016138016ea638106e800fe13831eccf1879317368d3073663463",
}


def test_the_digest_table_names_every_variant():
    assert set(ISLAND_DIGESTS) == set(ISLAND_VARIANTS)


@pytest.mark.parametrize("variant", ISLAND_VARIANTS)
def test_the_factory_writes_each_island_as_the_references_did(variant, tmp_path):
    files = island_files(variant)
    root = write_project(tmp_path / variant, files)
    assert tree_digest(root) == ISLAND_DIGESTS[variant]
    assert files_digest(files) == ISLAND_DIGESTS[variant]


def test_an_unknown_variant_is_refused():
    with pytest.raises(KeyError):
        island_files("lake")


def test_two_writes_give_the_same_tree(tmp_path):
    for variant in ISLAND_VARIANTS:
        first = write_project(tmp_path / "a" / variant, island_files(variant))
        second = write_project(tmp_path / "b" / variant, island_files(variant))
        names = sorted(p.relative_to(first) for p in first.rglob("*") if p.is_file())
        assert names == sorted(p.relative_to(second) for p in second.rglob("*") if p.is_file())
        for name in names:
            assert (first / name).read_bytes() == (second / name).read_bytes()


def test_the_factory_refuses_a_folder_that_holds_files(tmp_path):
    (tmp_path / "old.txt").write_text("x", encoding="utf-8")
    with pytest.raises(FileExistsError):
        write_project(tmp_path, {"project.toml": ""})
    with pytest.raises(ValueError):
        write_project(tmp_path / "other", {"../outside.toml": ""})


def test_the_isolated_env_hides_the_user_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HMP_BIN", "/elsewhere/bin")
    monkeypatch.setenv("HMP_WORKSPACE", "/elsewhere/workspace")
    monkeypatch.setenv("XDG_CACHE_HOME", "/elsewhere/cache")
    monkeypatch.setenv("MPLCONFIGDIR", "/elsewhere/mpl")
    monkeypatch.setenv("PYTHONPATH", "/elsewhere/python")
    env = isolated_env(tmp_path / "home", tmp_path / "cache", tmp_path / "state", tmp_path / "tmp")
    kept = {k for k in env if k.startswith(("HMP_", "XDG_"))}
    assert kept == {
        "HMP_CACHE_HOME",
        "HMP_STATE_HOME",
        "HMP_NO_PROGRESS",
        "HMP_DETERMINISTIC_FETCHED_AT",
    }
    assert "MPLCONFIGDIR" not in env
    assert Path(env["HOME"]).parent == tmp_path
    assert Path(env["HMP_STATE_HOME"]).parent == tmp_path
    assert env["OPENBLAS_NUM_THREADS"] == "1"
    assert (Path(env["PYTHONPATH"]) / "hydromodpy" / "__init__.py").is_file()


def test_the_launcher_plays_a_command_that_runs_nothing(tmp_path, scenario_env, scenario_cache):
    scenario = Scenario(
        name="version",
        covers="the launcher on a command that runs nothing",
        files={},
        argv=("--version",),
        needs=(),
    )
    played = play(scenario, tmp_path / "play", scenario_env, scenario_cache)
    assert played.returncode == 0
    assert played.targets == ()
    assert "hydromodpy" in played.log.read_text(encoding="utf-8")


def test_a_scenario_that_outlives_its_timeout_is_killed(tmp_path, scenario_env, scenario_cache):
    scenario = Scenario(
        name="slow",
        covers="the timeout of the launcher",
        files={},
        python="import time; time.sleep(60)",
        needs=(),
        timeout_s=1.0,
    )
    played = play(scenario, tmp_path / "play", scenario_env, scenario_cache)
    assert played.returncode == 124
    assert "timeout" in played.log.read_text(encoding="utf-8")
    assert played.seconds < 30


def test_a_scenario_that_fetches_a_binary_is_refused(tmp_path, scenario_env, scenario_cache):
    code = "import os, pathlib; pathlib.Path(os.environ['HMP_CACHE_HOME'], 'bin', 'mf6').touch()"
    scenario = Scenario(
        name="fetch",
        covers="the guard against a download",
        files={},
        python=code,
        needs=(),
    )
    with pytest.raises(AssertionError, match="fetch a solver binary"):
        play(scenario, tmp_path / "play", scenario_env, scenario_cache)


def test_a_scenario_needs_one_way_to_run():
    with pytest.raises(ValueError):
        Scenario(name="none", covers="nothing", files={})
    with pytest.raises(ValueError):
        Scenario(name="both", covers="nothing", files={}, argv=("run",), python="pass")


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="no symbolic links on this platform")
def test_binaries_are_linked_one_by_one(tmp_path, monkeypatch):
    machine = tmp_path / "machine"
    machine.mkdir()
    for name in ("mf6", "libmf6.so", "mfnwt"):
        (machine / name).write_text("", encoding="utf-8")
    (machine / ".manifest.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("HMP_BIN", str(machine))
    target = link_binaries(tmp_path / "cache", ("mf6", "libmf6.so"))
    assert sorted(p.name for p in target.iterdir()) == [".manifest.json", "libmf6.so", "mf6"]
    assert (target / "mf6").is_symlink()
    assert not target.is_symlink()
    with pytest.raises(pytest.skip.Exception):
        link_binaries(tmp_path / "cache", ("mf6", "mt3dusgs"))


def test_targets_are_found_by_their_files(tmp_path):
    run = tmp_path / "runs" / "a"
    session = tmp_path / "sessions" / "b"
    hidden = tmp_path / ".hmp" / "c"
    half = tmp_path / "runs" / "half"
    for folder, names in (
        (run, ("manifest.json", "fields.zarr")),
        (session, ("session.json", "trials.jsonl")),
        (hidden, ("manifest.json", "fields.zarr")),
        (half, ("manifest.json",)),
    ):
        folder.mkdir(parents=True)
        for name in names:
            (folder / name).write_text("", encoding="utf-8")
    assert find_targets(tmp_path) == (("run", "runs/a"), ("session", "sessions/b"))
