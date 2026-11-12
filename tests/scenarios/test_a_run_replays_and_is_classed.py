"""A run seals its values, replays them, and a run of a pre-release is read, replayed and classed.

One project folder, the transient island of ``factory.py`` played by MODFLOW 6,
then a copy of the frozen ``demo`` run of a pre-release. Four steps:

1. ``hmp run island.toml``: the seal is version 4, profile ``run``, carries the
   value rule ``values/1`` with one digest per array and per quantity column,
   seals the request id its outcome wrote and a solution key of its own,
   certifies ``products.json`` and ``final_state/``, and ``seal_problems``
   finds nothing to repair.
2. ``hmp replay runs/island --strict``: ``runs/island.v2/`` is sealed, its
   lineage is a replay of the island, class ``bit`` on the ``float64`` basis,
   and the values reproduce to the double.
3. ``hmp.compare`` reads the source and the replay side by side.
4. A copy of ``tests/regression/frozen_runs/v2.0.0/current``: ``hmp.open``
   reads ``runs/demo``, a version 3 seal, and ``hmp replay runs/demo`` writes a
   version 4 run whose lineage is a replay. Its class is measured on the stored
   values, since a version 3 seal keeps no value digest, and it is ``bit``.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import hydromodpy as hmp
from hydromodpy.results.record.manifest import RunSeal, read_seal, seal_problems
from tests.scenarios.factory import transient_island, write_project
from tests.scenarios.launcher import link_binaries

FROZEN = Path(__file__).resolve().parents[1] / "regression" / "frozen_runs" / "v2.0.0" / "current"
SOLVERS = ("mf6", "libmf6.so", "mfnwt", "mfnwtdbl")


def _hmp(root: Path, env: dict[str, str], *argv: str) -> subprocess.CompletedProcess[str]:
    """Run ``python -m hydromodpy`` in *root* with the environment of the scenario."""
    return subprocess.run(
        [sys.executable, "-m", "hydromodpy", *argv],
        cwd=root,
        env=dict(env),
        capture_output=True,
        text=True,
        timeout=600,
    )


def _said(result: subprocess.CompletedProcess[str]) -> str:
    """The tail of the run output, the part a failure prints."""
    return result.stderr[-3000:]


def test_a_run_replays_and_is_classed(
    tmp_path: Path, scenario_env: dict[str, str], scenario_cache: Path
) -> None:
    link_binaries(scenario_cache, SOLVERS)
    root = write_project(
        tmp_path / "project", {"island.toml": transient_island("island", "modflow6")}
    )

    # 1. One sealed run: version 4, its values, its two identities, its inventory.
    ran = _hmp(root, scenario_env, "run", "island.toml")
    assert ran.returncode == 0, _said(ran)
    source = root / "runs" / "island"
    seal = read_seal(source)
    assert isinstance(seal, RunSeal)
    assert seal.manifest_version == 4
    assert seal.profile == "run"
    assert seal.values is not None
    assert seal.values.rule == "values/1"
    keys = seal.values.digests
    assert "fields/head" in keys
    assert any(key.startswith("tables/") for key in keys)
    outcome = json.loads((source / "outcome.json").read_text(encoding="utf-8"))
    assert seal.identity.request_id == outcome["request_id"]
    assert seal.identity.solution_key is not None
    assert seal.identity.solution_key != seal.identity.request_id
    roles = {artifact.role for artifact in seal.artifacts}
    assert {"products", "final_state"} <= roles
    assert seal_problems(source) == []

    # 2. The same run played again, refusing a value that does not reproduce.
    replayed = _hmp(root, scenario_env, "replay", "runs/island", "--strict")
    assert replayed.returncode == 0, _said(replayed)
    replay_dir = root / "runs" / "island.v2"
    replay_seal = read_seal(replay_dir)
    assert replay_seal.manifest_version == 4
    assert replay_seal.lineage.kind == "replay"
    assert replay_seal.lineage.parent_sim_id == seal.identity.sim_id
    replay = replay_seal.lineage.replay
    assert replay is not None
    assert replay.of == seal.identity.sim_id
    assert replay.source == "run"
    assert replay.basis == "float64"
    assert replay.class_ == "bit"
    assert replay.strict is True
    assert replay.differs == {}
    assert replay.added == []
    assert replay.removed == []
    assert seal_problems(replay_dir) == []

    # 3. A replay is a run among the others: the comparison reads both.
    compared = hmp.compare(["island", "island.v2"], workspace=root)
    assert compared.tables["runs"]["run"].tolist() == ["island", "island.v2"]
    assert set(compared.tables) >= {"runs", "parameters", "scores", "budget"}

    # 4. A run sealed by a pre-release is read, replayed and classed.
    frozen = tmp_path / "frozen"
    shutil.copytree(FROZEN, frozen)
    project = frozen / "projects" / "example"
    demo = project / "runs" / "demo"
    on_disk = json.loads((demo / "manifest.json").read_text(encoding="utf-8"))
    assert on_disk["manifest_version"] == 3
    opened = hmp.open(demo)
    assert opened.name == "demo"
    assert isinstance(read_seal(demo), RunSeal)

    demo_replay = _hmp(project, scenario_env, "replay", "runs/demo")
    assert demo_replay.returncode == 0, _said(demo_replay)
    played_seal = read_seal(project / "runs" / "demo.v2")
    assert played_seal.manifest_version == 4
    assert played_seal.lineage.kind == "replay"
    played = played_seal.lineage.replay
    assert played is not None
    assert played.basis == "stored"
    assert played.source_version == "2.0.0rc1"
    # Measured on the stored values of both directories, every table included and
    # the wall-clock row of metrics left out: the frozen demo is exact, so its
    # replay reproduces it. The two final_state arrays and the open water mask are
    # what a pre-release did not write; they are listed and do not make a deviation.
    assert played.class_ == "bit", played.model_dump(mode="json", by_alias=True)
    assert played.differs == {}
    assert played.removed == []
    assert played.added == ["fields/mesh/open_water", "final_state/head", "final_state/lake_stage"]
