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

# Digests of the six islands, as the reference projects wrote them. A change of
# a project text changes its digest, so this table is edited with the text.
ISLAND_DIGESTS = {
    "gwt": "85a6c50d5a525986326544ec26114fdb5697b0fb3478919123479d58bf342e80",
    "nwt": "a217aa5ca3408dfa1484dfbb3836582df68b153647d1d0af31702e2bbda8302d",
    "boussinesq": "b8b8ea245c619d8bd9caf3a7670abda9e1eebc80ed6cc2b707942b8dd9b173b3",
    "spinup": "670b1e536a888265bb674c5a0adb9d2e913698479722740c46168d46a299fb89",
    "calage": "adfabb52dccea078761acab5ea53b6120aaba88a235c976d8b6b699071f54fb5",
    "calage_sy": "2b2e7d14cce593c58fdd2653cd998a8e3bc825463bbcec82480eb25887a4ff5c",
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


def test_a_scenario_that_fetches_a_binary_is_refused(tmp_path):
    code = "import os, pathlib; pathlib.Path(os.environ['HMP_CACHE_HOME'], 'bin', 'mf6').touch()"
    scenario = Scenario(
        name="fetch",
        covers="the guard against a download",
        files={},
        python=code,
        needs=(),
    )
    # Its own cache and environment: the scenario writes a file in the cache, and the
    # shared one, which links the real binaries, must stay clean.
    cache = tmp_path / "cache"
    env = isolated_env(tmp_path / "home", cache, tmp_path / "state", tmp_path / "tmp")
    with pytest.raises(AssertionError, match="fetch a solver binary"):
        play(scenario, tmp_path / "play", env, cache)


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
