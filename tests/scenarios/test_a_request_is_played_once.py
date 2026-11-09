"""A run request is played once, whatever form it comes in, on the transient island.

One project folder, played in order:
1. ``hmp run island.json --base .``: a request in JSON. The run is sealed, its
   ``request.json`` holds the request, its ``outcome.json`` the request id, and no
   copy of the file is left behind.
2. The same command again: the run is identical, the command says so and stops,
   and ``runs/`` holds no new version.
3. ``hmp.run`` on the same document as a dict with ``base=``, then on the same
   document written as ``island.toml``: both give back the run of step 1.
4. ``hmp run island.json --base . --set ...``: another request, so a new version.
5. ``hmp run broken.json --base .`` whose source is a URL nobody serves: the claim
   came first, so the failed attempt leaves its outcome.
"""

from __future__ import annotations

import json
import socket
import subprocess
import sys
import tomllib
from pathlib import Path

from tests.scenarios.factory import TRANSIENT
from tests.scenarios.launcher import Scenario, play

MF6_FILES = ("mf6", "libmf6.so")
SCHEMA = "hydromodpy.request.v1"


def _island_toml(name: str = "island") -> str:
    """Return the transient MODFLOW 6 island, named *name*."""
    return (
        TRANSIENT.replace("@NAME@", name)
        .replace("@SOLVER@", "modflow6")
        .replace("@TRANSPORT_PROCESS@", "")
    )


def _request(document: dict) -> str:
    """Return the JSON text of a run request holding *document*."""
    return json.dumps({"schema": SCHEMA, "config": document}, indent=2)


def _unserved_url() -> str:
    """Return a URL on the local host whose port no server listens on."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    return f"http://127.0.0.1:{port}/r.tif"


def _broken_document() -> dict:
    """Return the island whose recharge comes from a URL nobody serves."""
    document = tomllib.loads(_island_toml("broken"))
    document["data"]["types"] = ["oceanic", "recharge"]
    document["data"]["recharge"] = {
        "sources": [{"source": "url", "url": _unserved_url(), "sha256": "0" * 64}]
    }
    document["flow"]["sinks_sources"]["recharge"] = {}
    return document


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


def _runs(root: Path) -> list[str]:
    return sorted(path.name for path in (root / "runs").iterdir())


def _left_behind(root: Path) -> list[str]:
    """Every file a run wrote beside the files of the user: none is expected."""
    return sorted(
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if ".effective." in path.name or path.name.startswith(".hmp_effective")
    )


def test_a_request_is_played_once(
    tmp_path: Path, scenario_env: dict[str, str], scenario_cache: Path
) -> None:
    island = tomllib.loads(_island_toml())
    scenario = Scenario(
        name="request",
        covers="a run request in JSON, its skip, its dict and TOML forms, a version, a claim",
        files={
            "island.json": _request(island),
            "island.toml": _island_toml(),
            "broken.json": _request(_broken_document()),
        },
        argv=("run", "island.json", "--base", "."),
        needs=MF6_FILES,
    )

    # 1. One request in JSON, one sealed run.
    played = play(scenario, tmp_path / "play", scenario_env, scenario_cache)
    assert played.returncode == 0, played.log.read_text(encoding="utf-8")[-3000:]
    root = played.root
    run_dir = root / "runs" / "island"
    assert played.targets == (("run", "runs/island"),)
    kept = json.loads((run_dir / "request.json").read_text(encoding="utf-8"))
    assert (kept["schema"], kept["config"]) == (SCHEMA, island)
    outcome = json.loads((run_dir / "outcome.json").read_text(encoding="utf-8"))
    assert outcome["status"] == "completed"
    assert len(outcome["request_id"]) == 64
    assert (run_dir / "config.toml").is_file()
    assert _left_behind(root) == []

    # 2. The same request again is given back, and leaves no directory.
    again = _hmp(root, scenario_env, "run", "island.json", "--base", ".")
    assert again.returncode == 0, again.stderr[-3000:]
    assert "Config identical to completed run 'island'" in again.stderr
    assert _runs(root) == ["island"]

    # 3. The same document as a dict, then as a TOML file, is the same request.
    answer = root / "answer.json"
    api = subprocess.run(
        [
            sys.executable,
            "-c",
            "import json, sys\n"
            "import hydromodpy as hmp\n"
            "document = json.load(open('island.json'))['config']\n"
            "from_dict = hmp.run(document, base='.')\n"
            "from_toml = hmp.run('island.toml')\n"
            f"json.dump([from_dict.sim_id, from_toml.sim_id], open({str(answer)!r}, 'w'))\n",
        ],
        cwd=root,
        env=dict(scenario_env),
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert api.returncode == 0, api.stderr[-3000:]
    assert json.loads(answer.read_text(encoding="utf-8")) == [outcome["sim_id"]] * 2
    assert _runs(root) == ["island"]

    # 4. A change of the request is another request: a new version of the run.
    changed = _hmp(
        root,
        scenario_env,
        "run",
        "island.json",
        "--base",
        ".",
        "--set",
        'flow.param.K.field.value="2e-5 m/s"',
    )
    assert changed.returncode == 0, changed.stderr[-3000:]
    assert _runs(root) == ["island", "island.v2"]
    assert (root / "runs" / "island.v2" / "manifest.json").is_file()
    second = json.loads((root / "runs" / "island.v2" / "outcome.json").read_text("utf-8"))
    assert second["request_id"] != outcome["request_id"]
    played_set = json.loads((root / "runs" / "island.v2" / "request.json").read_text("utf-8"))
    assert played_set["set"] == {"flow.param.K.field.value": "2e-5 m/s"}

    # 5. The claim comes before the inputs: a source that fails leaves its outcome.
    broken = _hmp(
        root, scenario_env, "run", "broken.json", "--base", ".", "--allow-host", "127.0.0.1"
    )
    assert broken.returncode == 16, broken.stderr[-3000:]
    failed = json.loads((root / "runs" / "broken" / "outcome.json").read_text("utf-8"))
    assert failed["status"] == "failed"
    assert (root / "runs" / "broken" / "request.json").is_file()
    assert _left_behind(root) == []
