"""The five ways a run starts, played through the real pipeline on the island.

Three runs start from the steady solve of their own solver, one from the last of
repeated cycles of its own period, and one from the final head of an earlier run
that it names. Each scenario checks that the run closes and that the start state
reached the heads.
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pytest
import zarr

from hydromodpy.core.fields.nodata import SENTINEL_ABS_THRESHOLD
from hydromodpy.results.storage.prior_state import read_final_head
from tests.scenarios.factory import (
    INITIAL_STATE_VARIANTS,
    initial_state_files,
    tree_digest,
    write_project,
)
from tests.scenarios.launcher import Scenario, play

RESTART_CHAIN = """\
import subprocess, sys
for name in ("prior.toml", "resumed.toml", "cold.toml"):
    subprocess.run([sys.executable, "-m", "hydromodpy", "run", name], check=True)
"""

MF6_FILES = ("mf6", "libmf6.so")

STEADY_SCENARIOS = {
    "steady_ic_modflow6": ("MODFLOW 6", MF6_FILES),
    "steady_ic_nwt": ("MODFLOW-NWT", (*MF6_FILES, "mfnwt")),
    "steady_ic_boussinesq": ("Boussinesq", MF6_FILES),
}


def _first_head(fields: Path) -> np.ndarray:
    """Return the head of the first time step, ``(nlay, ncpl)``, NaN where the store has none."""
    head = np.asarray(zarr.open(str(fields), mode="r")["head"][0], dtype=float)
    head = head.reshape(head.shape[0], -1)
    return np.where(np.abs(head) > SENTINEL_ABS_THRESHOLD, np.nan, head)


def _runs(played) -> dict[str, Path]:
    """Return the run folders a played scenario left, by run name."""
    return {Path(path).name: played.root / path for kind, path in played.targets if kind == "run"}


def test_the_factory_writes_each_start_the_same_way_twice(tmp_path: Path) -> None:
    for variant in INITIAL_STATE_VARIANTS:
        first = write_project(tmp_path / "a" / variant, initial_state_files(variant))
        second = write_project(tmp_path / "b" / variant, initial_state_files(variant))
        assert tree_digest(first) == tree_digest(second)
    with pytest.raises(KeyError):
        initial_state_files("lake")


@pytest.mark.parametrize("variant", sorted(STEADY_SCENARIOS))
def test_a_run_started_from_its_own_steady_solve_closes(
    variant, tmp_path, scenario_env, scenario_cache
) -> None:
    solver, needs = STEADY_SCENARIOS[variant]
    scenario = Scenario(
        name=variant,
        covers=f"a {solver} run whose start is the steady solve of {solver}",
        files=initial_state_files(variant),
        argv=("run", "project.toml"),
        needs=needs,
    )

    played = play(scenario, tmp_path / "play", scenario_env, scenario_cache)

    assert played.returncode == 0, played.log.read_text(encoding="utf-8")[-2000:]
    runs = _runs(played)
    assert list(runs) == [variant]
    head = _first_head(runs[variant] / "fields.zarr")
    assert np.isfinite(head).any()


def test_a_cyclic_start_reports_how_many_cycles_it_ran(tmp_path, scenario_env, scenario_cache):
    scenario = Scenario(
        name="cyclic_ic",
        covers="a MODFLOW 6 run whose start is the last of three repeated cycles",
        files=initial_state_files("cyclic_ic"),
        argv=("run", "project.toml"),
    )

    played = play(scenario, tmp_path / "play", scenario_env, scenario_cache)

    log = played.log.read_text(encoding="utf-8")
    assert played.returncode == 0, log[-2000:]
    said = re.search(r"settled after (\d+) cycle|ran its (\d+) allowed cycle", log)
    assert said is not None, "the run does not say how many cycles it ran"
    assert 2 <= int(said.group(1) or said.group(2)) <= 3
    assert list(_runs(played)) == ["cyclic_ic"]


def test_a_run_restarted_by_name_starts_from_the_final_head_of_the_first(
    tmp_path, scenario_env, scenario_cache
) -> None:
    scenario = Scenario(
        name="restart",
        covers="a second MODFLOW 6 run that names the first in flow.restart_from",
        files=initial_state_files("restart"),
        python=RESTART_CHAIN,
        expected_s=30.0,
    )

    played = play(scenario, tmp_path / "play", scenario_env, scenario_cache)

    assert played.returncode == 0, played.log.read_text(encoding="utf-8")[-2000:]
    runs = _runs(played)
    assert sorted(runs) == ["cold", "prior", "resumed"]
    final = read_final_head(str(runs["prior"] / "fields.zarr"))
    resumed = _first_head(runs["resumed"] / "fields.zarr")
    cold = _first_head(runs["cold"] / "fields.zarr")
    active = np.isfinite(final) & np.isfinite(resumed) & np.isfinite(cold)
    assert active.any()
    from_the_restart = np.abs(resumed - final)[active].max()
    from_the_top = np.abs(cold - final)[active].max()
    assert from_the_restart < from_the_top / 4.0
