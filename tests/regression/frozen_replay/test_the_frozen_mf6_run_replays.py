"""The frozen MODFLOW 6 run on triangles replays to the bit, on this machine and on another.

``v2.0.0/current`` holds ``tri.toml`` and the run ``runs/tri/`` that ``python -m
tools.freeze_replay_run`` wrote: the transient island on 434 gmsh triangles, three
months, XT3D off. A replay reads the mesh sealed in the run, so it needs neither gmsh
nor the store. Each test works on a copy outside the repository.

The replay is played without ``--strict``. A processor that rounds differently must
seal its replay and measure the gap, not be refused. When ``HMP_REPLAY_REPORT`` names a
file, the replay writes there what it measured before any assertion, so the weekly job
can upload the numbers on a runner whose class is not ``bit``.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from hydromodpy.results.record.manifest import seal_problems
from hydromodpy.solver.modflow_common.binaries import exe_filename
from tests.scenarios.launcher import isolated_env, link_binaries

FROZEN = Path(__file__).resolve().parent / "v2.0.0"
CURRENT = FROZEN / "current"
MAX_BYTES = 600_000
RUN = "runs/tri"
REPLAY_TIMEOUT_S = 600
REPORT_VARIABLE = "HMP_REPLAY_REPORT"


def _tree_digest(tree: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in tree.rglob("*") if item.is_file()):
        digest.update(path.relative_to(tree).as_posix().encode("utf-8"))
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def expected() -> dict[str, Any]:
    """What the generator said about the run when it wrote it."""
    return _json(FROZEN / "expected.json")


@pytest.fixture(scope="module")
def frozen_copy(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A copy of ``current/`` that the tests that only read share."""
    target = tmp_path_factory.mktemp("frozen") / "copy"
    shutil.copytree(CURRENT, target)
    return target


def _replay(folder: Path, *, without_gmsh: bool) -> dict[str, Any]:
    """Replay the run of a copy in a child process and return its lineage block.

    The child has a home, a state and a cache of its own, ``mf6`` linked into the
    cache and no ``.hmp`` index. With ``without_gmsh`` a module named ``gmsh`` that
    raises on import comes first on the path, so a replay that needs the mesher fails.
    """
    work = folder.parent / "replay_env"
    cache = work / "cache"
    link_binaries(cache, (exe_filename("mf6"),))
    env = isolated_env(work / "home", cache, work / "state", work / "tmp")
    if without_gmsh:
        blocked = work / "blocked"
        blocked.mkdir()
        (blocked / "gmsh.py").write_text("raise ImportError('gmsh is not importable')\n")
        env["PYTHONPATH"] = os.pathsep.join([str(blocked), env["PYTHONPATH"]])
    done = subprocess.run(
        [sys.executable, "-m", "hydromodpy", "replay", RUN],
        cwd=folder,
        env=env,
        capture_output=True,
        text=True,
        timeout=REPLAY_TIMEOUT_S,
        check=False,
    )
    assert done.returncode == 0, f"hmp replay exited with {done.returncode}:\n{done.stderr[-3000:]}"
    manifest = _json(folder / "runs" / "tri.v2" / "manifest.json")
    return {"lineage": manifest["lineage"]["replay"], "manifest": manifest}


def _write_report(replay: dict[str, Any], folder: Path) -> None:
    """Write the measure of a replay where ``HMP_REPLAY_REPORT`` says, before any assertion."""
    target = os.environ.get(REPORT_VARIABLE)
    if not target:
        return
    solver = _json(folder / "runs" / "tri.v2" / "provenance.json")["solver"]
    lineage = replay["lineage"]
    report = {
        "class": lineage["class"],
        "basis": lineage["basis"],
        "differs": lineage["differs"],
        "platform": platform.platform(),
        "python": platform.python_version(),
        "numpy": np.__version__,
        "mf6": solver.get("version"),
    }
    Path(target).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


@pytest.fixture(scope="module")
def replayed(frozen_copy: Path) -> dict[str, Any]:
    """The replay of the copy, played once for the tests that read its lineage."""
    replay = _replay(frozen_copy, without_gmsh=False)
    _write_report(replay, frozen_copy)
    return replay


def _gaps(differs: dict[str, Any]) -> str:
    return "\n".join(f"  {name}: {gap}" for name, gap in sorted(differs.items())) or "  none"


def test_the_frozen_bytes_have_not_moved(expected: dict[str, Any]) -> None:
    assert _tree_digest(CURRENT) == expected["tree_sha256"]


def test_the_frozen_run_stays_small() -> None:
    total = sum(item.stat().st_size for item in CURRENT.rglob("*") if item.is_file())
    assert total < MAX_BYTES, f"the frozen run weighs {total} bytes, the limit is {MAX_BYTES}"


def test_the_frozen_run_holds_its_seal(frozen_copy: Path) -> None:
    assert seal_problems(frozen_copy / RUN) == []


def test_the_frozen_run_names_no_home() -> None:
    markers = (b"/home/", b"C:\\Users")
    named = [
        path.relative_to(CURRENT).as_posix()
        for path in sorted(CURRENT.rglob("*"))
        if path.is_file() and any(marker in path.read_bytes() for marker in markers)
    ]
    assert named == [], f"these files name a home folder: {named}"


def test_the_frozen_run_replays_bit(replayed: dict[str, Any], expected: dict[str, Any]) -> None:
    lineage, manifest = replayed["lineage"], replayed["manifest"]
    assert lineage["of"] == expected["sim_id"]
    assert (manifest["geometry"]["n_cells"], manifest["period"]["n_timesteps"]) == (
        expected["cells"],
        expected["periods"],
    )
    assert lineage["class"] == "bit" and lineage["basis"] == "float64", (
        f"the replay is class {lineage['class']} on {lineage['basis']}, and differs in:\n"
        f"{_gaps(lineage['differs'])}"
    )
    assert (lineage["differs"], lineage["added"], lineage["removed"]) == ({}, [], [])
    assert manifest["values"]["digests"] == expected["values"]


def test_the_replay_needs_no_gmsh(tmp_path: Path) -> None:
    copy = tmp_path / "copy"
    shutil.copytree(CURRENT, copy)
    lineage = _replay(copy, without_gmsh=True)["lineage"]
    assert (lineage["class"], lineage["differs"]) == ("bit", {}), _gaps(lineage["differs"])
