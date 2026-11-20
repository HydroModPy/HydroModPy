"""The run a lab keeps is the run its file gives for the same change.

One folder holds two copies of the MODFLOW 6 island. The lab of the first changes K,
solves, and keeps its model as a run, which takes the solve of the lab instead of
solving again. ``hmp.run`` plays the second with the same change. Both seals hold
the same values, configuration, inputs, parameters and solution key, and the same
stored heads. A lab opened on the run of the file then keeps the same values again.
A lab built from a run has no file of its own, so ``config.source`` is left out there.
A third copy is built in a lab section after section, from [geographic] and [data]
alone, and its run holds the values and the solution key of the file again.
"""

from __future__ import annotations

import json
from pathlib import Path

from tests.scenarios.factory import TRANSIENT
from tests.scenarios.launcher import play_script

MF6_FILES = ("mf6", "libmf6.so")
SEALED = ("values", "config", "inputs", "parameters", "lineage")

SCRIPT = """
import json
import tomllib
import hydromodpy as hmp

EXECUTE = "hydromodpy/solver/base/runner.py:SimulationRunner.execute"
hmp.run("file/island.toml", name="kept", set={"K": 5e-5})
lab = hmp.Lab("lab/island.toml")
lab.set(K=5e-5)
lab.solve()
with lab.capture(EXECUTE) as seen:
    lab.run("kept")
lab.set(K=2e-5)
after = lab.solve()
lab.close()
reopened = hmp.Lab(hmp.open("file/runs/kept"))
built = list(reopened.steps.status).count("built")
reopened.advance("run_solver")
with reopened.capture(EXECUTE) as seen_again:
    reopened.run("again")
reopened.close()
doc = tomllib.loads(open("draft/island.toml").read())
doc["data"].pop("types")
draft = hmp.Lab({"geographic": doc["geographic"], "data": doc["data"]}, base="draft")
draft.advance("build_geographic")
draft.set(domain=doc["domain"])
draft.advance("build_mesh")
doc["flow"]["param"]["K"]["field"]["value"] = "5e-5 m/s"
rest = {k: doc[k] for k in ("flow", "simulation", "site", "workflow", "display")}
draft.set(**rest)
draft.advance("run_solver")
draft.run("kept")
draft.close()
report = {
    "solves": len(seen[EXECUTE]),
    "again": len(seen_again[EXECUTE]),
    "after": [r.solved for r in after.values()],
    "built": built,
}
with open("seen.json", "w") as file:
    json.dump(report, file)
"""


def _run(root: Path, folder: str, name: str) -> Path:
    return root / folder / "runs" / name


def _manifest(run: Path) -> dict:
    return json.loads((run / "manifest.json").read_text("utf-8"))


def _heads(run: Path) -> dict[str, bytes]:
    folder = run / "fields.zarr" / "head"
    files = sorted(path for path in folder.rglob("*") if path.is_file())
    return {str(path.relative_to(folder)): path.read_bytes() for path in files}


def _solves(run: Path) -> list[str]:
    lines = json.loads((run / "profile.json").read_text("utf-8"))["lines"]
    return [line["name"] for line in lines if line["kind"] == "solve"]


def test_a_lab_run_is_the_run_of_its_file(
    tmp_path: Path, scenario_env: dict[str, str], scenario_cache: Path
) -> None:
    island = TRANSIENT.replace("@NAME@", "island").replace("@SOLVER@", "modflow6")
    island = island.replace("@TRANSPORT_PROCESS@", "")
    played = play_script(
        "lab_run",
        {"lab/island.toml": island, "file/island.toml": island, "draft/island.toml": island},
        SCRIPT,
        tmp_path / "play",
        scenario_env,
        scenario_cache,
        needs=MF6_FILES,
    )
    assert played.returncode == 0, played.log.read_text(encoding="utf-8")[-3000:]

    lab_run, file_run = _run(played.root, "lab", "kept"), _run(played.root, "file", "kept")
    from_lab, from_file = _manifest(lab_run), _manifest(file_run)
    for section in SEALED:
        assert from_lab[section] == from_file[section], section
    assert from_lab["identity"]["solution_key"] == from_file["identity"]["solution_key"]
    assert from_lab["values"]
    assert _heads(lab_run) and _heads(lab_run) == _heads(file_run)
    assert len(_solves(lab_run)) == 1 and _solves(lab_run) == _solves(file_run)
    from_draft = _manifest(_run(played.root, "draft", "kept"))
    assert from_draft["values"] == from_file["values"]
    assert from_draft["identity"]["solution_key"] == from_file["identity"]["solution_key"]

    seen = json.loads((played.root / "seen.json").read_text("utf-8"))
    assert seen == {"solves": 0, "again": 0, "after": [True], "built": 0}
    again = _manifest(_run(played.root, "file", "again"))
    for section in ("values", "inputs", "parameters"):
        assert again[section] == from_file[section], section
    assert again["identity"]["solution_key"] == from_file["identity"]["solution_key"]
