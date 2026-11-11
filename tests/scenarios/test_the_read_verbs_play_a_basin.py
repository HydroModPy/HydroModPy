"""The read verbs of ``hmp`` play the basin of the global backend, one after the other.

One project folder, played in order:
1. ``hmp run project.toml``, then again with ``--force``: two sealed runs,
   ``basin`` and ``basin.v2``.
2. ``hmp ls`` lists both, ``hmp show basin`` reads the summary of the run,
   ``--profile`` where its time went, ``--figure hydrograph`` draws one figure.
3. ``hmp diff basin basin.v2`` compares them, ``hmp export basin discharge``
   writes the series.
4. ``hmp catalog ls``, a form that left in 2.1.0, exits 2 with the command that
   replaces it.

The global backend needs no solver binary.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from tests.scenarios.factory import basin_files
from tests.scenarios.launcher import Scenario, play


def _hmp(root: Path, env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    """Run ``python -m hydromodpy`` in *root* with the environment of the scenario."""
    return subprocess.run(
        [sys.executable, "-m", "hydromodpy", *args],
        cwd=root,
        env=dict(env),
        capture_output=True,
        text=True,
        timeout=600,
    )


def test_the_read_verbs_play_a_basin(
    tmp_path: Path, scenario_env: dict[str, str], scenario_cache: Path
) -> None:
    scenario = Scenario(
        name="read_verbs",
        covers="hmp ls, show, diff and export on two runs of a basin, and a refused old form",
        files=basin_files(),
        argv=("run", "project.toml"),
        needs=(),
    )

    # 1. Two sealed runs of one basin.
    played = play(scenario, tmp_path / "play", scenario_env, scenario_cache)
    assert played.returncode == 0, played.log.read_text(encoding="utf-8")[-3000:]
    root = played.root
    again = _hmp(root, scenario_env, "run", "project.toml", "--force")
    assert again.returncode == 0, again.stderr[-3000:]
    assert sorted(path.name for path in (root / "runs").iterdir()) == ["basin", "basin.v2"]

    # 2. The list, the summary, the profile and one figure.
    listed = _hmp(root, scenario_env, "ls", "--format", "json")
    assert listed.returncode == 0, listed.stderr[-3000:]
    assert {"basin", "basin.v2"} <= {line["name"] for line in json.loads(listed.stdout)["data"]}
    shown = _hmp(root, scenario_env, "show", "basin")
    assert shown.returncode == 0, shown.stderr[-3000:]
    assert "basin" in shown.stdout
    profile = _hmp(root, scenario_env, "show", "basin", "--profile")
    assert profile.returncode == 0, profile.stderr[-3000:]
    drawn = _hmp(root, scenario_env, "show", "basin", "--figure", "hydrograph")
    assert drawn.returncode == 0, drawn.stderr[-3000:]
    # A name reads its latest version, so the figure lands under basin.v2.
    assert list((root / "runs" / "basin.v2" / "figures").glob("hydrograph*"))

    # 3. The comparison and the export.
    compared = _hmp(root, scenario_env, "diff", "basin", "basin.v2")
    assert compared.returncode == 0, compared.stderr[-3000:]
    exported = _hmp(root, scenario_env, "export", "basin", "discharge")
    assert exported.returncode == 0, exported.stderr[-3000:]
    assert list((root / "runs" / "basin.v2").rglob("*discharge*"))

    # 4. A form that left is refused with the one that replaces it.
    refused = _hmp(root, scenario_env, "catalog", "ls")
    assert refused.returncode == 2
    assert "hmp ls" in refused.stderr
