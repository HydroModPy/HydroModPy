"""A check beside a run that warns keeps its own warning and takes nothing of the run.

A validator says its warning through ``core/config_kit/said.py``. A run in the
main thread loads a document whose layering warns, while a second thread checks
another document over and over, whose layering warns with other words. Each
check must give exactly its own warning and none of the run's, and the run keeps
its own in its log.
"""

from __future__ import annotations

import json

from tests.scenarios.factory import island_files
from tests.scenarios.launcher import Scenario, play

RUN_WORDS = "genmtd_lay='list'"
CHECK_WORDS = "genmtd_lay='surfaces'"

LAYERED_BY_PROPORTIONS = """\
[domain.layers]
genmtd_lay = "list"
lay_proportions = [1.0]
nlay = 1
"""

CHILD = """\
import json
import threading
from pathlib import Path

import hydromodpy as hmp

CHECKED = {
    "geographic": {"source_mode": "synthetic"},
    "domain": {"layers": {"genmtd_lay": "surfaces", "layer": [{"name": "rock"}], "nlay": 5}},
}
base = Path(".").resolve()
box = {"stop": False, "checks": [], "errors": []}


def keep_checking():
    try:
        while not box["stop"]:
            found = hmp.check(CHECKED, base=base)
            box["checks"].append(sorted(d.detail for d in found if d.code == "section_warning"))
    except BaseException as error:
        box["errors"].append(repr(error))


thread = threading.Thread(target=keep_checking)
thread.start()
try:
    outcome = hmp.run("project.toml")
finally:
    box["stop"] = True
    thread.join()
box["run_dir"] = str(outcome.run_dir)
Path("beside.json").write_text(json.dumps(box), encoding="utf-8")
"""


def _island_that_warns() -> dict[str, str]:
    files = dict(island_files("gwt"))
    text = files["project.toml"]
    assert text.count("[domain.layers]\nnlay = 1\n") == 1
    files["project.toml"] = text.replace("[domain.layers]\nnlay = 1\n", LAYERED_BY_PROPORTIONS)
    return files


def test_a_check_beside_a_run_that_warns_keeps_its_own_warning(
    tmp_path, scenario_env, scenario_cache
):
    scenario = Scenario(
        name="island",
        covers="hmp.check repeated in a second thread beside a run whose document warns",
        files=_island_that_warns(),
        python=CHILD,
        needs=("mf6", "libmf6.so"),
    )

    played = play(scenario, tmp_path / "play", scenario_env, scenario_cache)

    assert played.returncode == 0, played.log.read_text(encoding="utf-8")[-2000:]
    box = json.loads((played.root / "beside.json").read_text(encoding="utf-8"))
    assert box["errors"] == []
    assert box["checks"], "the second thread never finished a check"
    for warned in box["checks"]:
        assert len(warned) == 1
        assert CHECK_WORDS in warned[0]
        assert RUN_WORDS not in warned[0]
    assert RUN_WORDS in played.log.read_text(encoding="utf-8"), "the run lost its own warning"
